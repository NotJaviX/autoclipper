import json
import logging
import re
import time
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)

from twitch_vod.client import TwitchVodClient
from twitch_vod.config import TwitchConfig
from twitch_vod.api.gql_client import TwitchGQLClient, TwitchGQLError
from twitch_vod.models.chat import ChatMessage
from yt_dlp import YoutubeDL


def _formatear_tiempo(segundos):
    segundos = int(segundos)
    horas, resto = divmod(segundos, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


def _guardar_estado(ruta_estado, vod_id, inicio_segundos, fin_segundos, offset):
    ruta_temporal = ruta_estado.with_name(ruta_estado.name + ".tmp")
    ruta_temporal.write_text(
        json.dumps(
            {
                "vod_id": vod_id,
                "inicio_segundos": inicio_segundos,
                "fin_segundos": fin_segundos,
                "siguiente_offset": offset,
            }
        ),
        encoding="utf-8",
    )
    ruta_temporal.replace(ruta_estado)


def descargar_video(url, output_path):
    print(f"Descargando vídeo de {url}...")
    opciones = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "outtmpl": output_path,
    }
    with YoutubeDL(opciones) as ydl:
        resultado = ydl.download([url])
    if resultado:
        raise RuntimeError(f"yt-dlp terminó con código {resultado}.")
    print("Vídeo descargado.")


def descargar_chat(
    url,
    output_path,
    client_id,
    client_secret,
    inicio_segundos=0,
    fin_segundos=None,
):
    print(
        f"Descargando historial del chat desde {inicio_segundos}s"
        + (f" hasta {fin_segundos}s..." if fin_segundos is not None else "...")
    )
    id_vod = re.search(r"/videos/(\d+)", url)
    if not id_vod:
        raise ValueError(f"No se pudo extraer el ID del VOD de Twitch desde: {url}")

    if not client_id or not client_secret:
        raise ValueError(
            "Define TWITCH_CLIENT_ID y TWITCH_CLIENT_SECRET en main.py antes "
            "de descargar el chat."
        )
    if inicio_segundos < 0 or (
        fin_segundos is not None and fin_segundos <= inicio_segundos
    ):
        raise ValueError("El rango del chat debe tener tiempos válidos y crecientes.")

    ruta_salida = Path(output_path)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_progreso = ruta_salida.with_name(ruta_salida.name + ".progress.jsonl")
    ruta_estado = ruta_salida.with_name(ruta_salida.name + ".progress.json")
    ruta_cache = ruta_salida.parent / ".twitch_vod_cache_range"
    configuracion = TwitchConfig(
        client_id=client_id,
        client_secret=client_secret,
        output_dir=ruta_cache,
    )

    with TwitchVodClient(configuracion) as cliente:
        vod = cliente.get_vod_metadata(id_vod.group(1))
    if fin_segundos is not None and fin_segundos > vod.duration:
        raise ValueError(
            f"El final solicitado ({fin_segundos}s) supera la duración "
            f"del VOD ({vod.duration}s)."
        )

    mensajes = []
    vistos = set()
    offset = int(inicio_segundos)
    if ruta_estado.exists() or ruta_progreso.exists():
        if not ruta_estado.exists() or not ruta_progreso.exists():
            raise RuntimeError(
                "El progreso guardado está incompleto; no se ha modificado. "
                f"Revisa {ruta_estado} y {ruta_progreso}."
            )
        estado = json.loads(ruta_estado.read_text(encoding="utf-8"))
        rango_guardado = (
            estado.get("vod_id"),
            estado.get("inicio_segundos"),
            estado.get("fin_segundos"),
        )
        rango_solicitado = (id_vod.group(1), inicio_segundos, fin_segundos)
        if rango_guardado != rango_solicitado:
            raise RuntimeError(
                "El progreso guardado pertenece a otro VOD o intervalo; "
                "no se ha reutilizado."
            )
        offset = int(estado["siguiente_offset"])
        with ruta_progreso.open("r", encoding="utf-8") as archivo:
            for linea in archivo:
                registro = json.loads(linea)
                mensajes.append(registro["mensaje"])
                if registro.get("id") is not None:
                    vistos.add(registro["id"])
        print(
            f"Reanudando desde {_formatear_tiempo(offset)} "
            f"con {len(mensajes)} mensajes guardados."
        )
    else:
        _guardar_estado(
            ruta_estado, id_vod.group(1), inicio_segundos, fin_segundos, offset
        )
        ruta_progreso.touch()
    paginas = 0
    fin_progreso = fin_segundos if fin_segundos is not None else vod.duration
    duracion_rango = max(fin_progreso - inicio_segundos, 1)
    with TwitchGQLClient() as gql:
        while offset < fin_progreso:
            for intento in range(5):
                try:
                    respuesta = gql.fetch_chat_by_offset(id_vod.group(1), offset)
                    break
                except TwitchGQLError as error:
                    if "service error" not in str(error).lower() or intento == 4:
                        raise
                    espera = min(2 ** intento, 30)
                    print(
                        f"\nTwitch devolvió un error temporal; "
                        f"reintentando en {espera}s (intento {intento + 2}/5)."
                    )
                    time.sleep(espera)
            if not isinstance(respuesta, list) or not respuesta:
                raise RuntimeError("Twitch devolvió una respuesta de chat vacía o inválida.")

            pagina = respuesta[0]
            comentarios = (
                pagina.get("data", {}).get("video", {}).get("comments")
                if isinstance(pagina, dict)
                else None
            )
            if not isinstance(comentarios, dict):
                raise RuntimeError(
                    "No se pudo leer la página de chat devuelta por Twitch."
                )

            edges = comentarios.get("edges", [])
            if not edges:
                break

            ultimo_tiempo = offset
            fin_alcanzado = False
            mensajes_pagina = []
            for edge in edges:
                nodo = edge.get("node", {}) if isinstance(edge, dict) else {}
                tiempo = nodo.get("contentOffsetSeconds")
                if not isinstance(tiempo, (int, float)):
                    continue
                ultimo_tiempo = max(ultimo_tiempo, int(tiempo))
                if tiempo >= fin_progreso:
                    fin_alcanzado = True
                    break

                mensaje_id = nodo.get("id")
                if mensaje_id and mensaje_id in vistos:
                    continue
                if mensaje_id:
                    vistos.add(mensaje_id)

                mensaje = ChatMessage.from_gql_node(nodo)
                if mensaje and mensaje.timestamp >= inicio_segundos:
                    registro = {
                        "id": mensaje_id,
                        "mensaje": {
                            "time_in_seconds": mensaje.timestamp,
                            "message": mensaje.content,
                        },
                    }
                    mensajes_pagina.append(registro)
                    mensajes.append(registro["mensaje"])

            paginas += 1
            porcentaje = min(
                99.9,
                max(0, (ultimo_tiempo - inicio_segundos) / duracion_rango * 100),
            )
            tiempo_mostrado = min(ultimo_tiempo, fin_progreso)
            print(
                f"\rProgreso del chat: {porcentaje:5.1f}% "
                f"| {_formatear_tiempo(tiempo_mostrado)} / "
                f"{_formatear_tiempo(fin_progreso)} "
                f"| Páginas: {paginas} | Mensajes: {len(mensajes)}",
                end="",
                flush=True,
            )
            siguiente_pagina = comentarios.get("pageInfo", {}).get(
                "hasNextPage", False
            )
            fin_alcanzado = fin_alcanzado or ultimo_tiempo >= fin_progreso
            siguiente_offset = (
                ultimo_tiempo if ultimo_tiempo > offset else offset + 1
            )
            if fin_alcanzado or not siguiente_pagina:
                siguiente_offset = fin_progreso
            with ruta_progreso.open("a", encoding="utf-8") as archivo:
                for registro in mensajes_pagina:
                    if registro["id"] is not None:
                        vistos.add(registro["id"])
                    archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
                archivo.flush()
            _guardar_estado(
                ruta_estado,
                id_vod.group(1),
                inicio_segundos,
                fin_segundos,
                siguiente_offset,
            )
            if fin_alcanzado or not siguiente_pagina:
                break

            offset = siguiente_offset

    print()
    if not mensajes:
        raise RuntimeError(
            "No se encontraron mensajes en el rango indicado. "
            "Comprueba que el VOD tiene chat replay disponible."
        )

    mensajes.sort(key=lambda mensaje: mensaje["time_in_seconds"])
    with ruta_salida.open("w", encoding="utf-8") as archivo:
        json.dump(
            mensajes,
            archivo,
            ensure_ascii=False,
            indent=2,
        )
    ruta_progreso.unlink()
    ruta_estado.unlink()
    print(
        f"Progreso del chat: 100.0% | {_formatear_tiempo(fin_progreso)} "
        f"| Páginas en esta ejecución: {paginas}"
    )
    print(f"Chat descargado: {len(mensajes)} mensajes en {paginas} páginas.")