import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from src.downloader import descargar_video, descargar_chat
from src.analyzer import analizar_chat
from src.editor import crear_clip_pantalla_dividida

load_dotenv(Path(__file__).resolve().parent / ".env")

# 1. CONFIGURACIÓN
DURACION_CLIP = 20
SEGUNDOS_ANTES_DEL_PICO = 10
TOP_N_CLIPS = 20

CHAT_INICIO_SEGUNDOS = 60 * 60
CHAT_FIN_SEGUNDOS = None


def cargar_configuracion_stream(ruta_config=None):
    if ruta_config is None:
        ruta_config = Path(__file__).resolve().parent / "configs" / "speed.json"

    ruta_config = Path(ruta_config)
    nombre_perfil = ruta_config.stem
    if not re.fullmatch(r"[A-Za-z0-9_-]+", nombre_perfil):
        raise ValueError(
            "El nombre del archivo de configuración solo puede contener "
            "letras ASCII, números, guiones y guiones bajos."
        )

    with ruta_config.open("r", encoding="utf-8") as archivo:
        configuracion = json.load(archivo)

    if not isinstance(configuracion, dict):
        raise ValueError("La configuración del stream debe ser un objeto JSON.")
    url = configuracion.get("url")
    camara = configuracion.get("camera")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("La configuración debe incluir una URL no vacía.")
    if not isinstance(camara, dict):
        raise ValueError("La configuración debe incluir el objeto 'camera'.")

    coordenadas = {}
    for clave in ("x", "y", "w", "h"):
        valor = camara.get(clave)
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ValueError(f"La coordenada camera.{clave} debe ser un entero.")
        if (clave in ("x", "y") and valor < 0) or (
            clave in ("w", "h") and valor <= 0
        ):
            raise ValueError(f"La coordenada camera.{clave} debe ser positiva.")
        coordenadas[clave] = valor

    return nombre_perfil, url.strip(), coordenadas


def main(ruta_config=None):
    nombre_perfil, url_stream, coords_camara = cargar_configuracion_stream(
        ruta_config
    )
    directorio_workspace = Path("workspace")
    if nombre_perfil:
        directorio_workspace /= nombre_perfil
    directorio_workspace.mkdir(parents=True, exist_ok=True)

    if nombre_perfil:
        ruta_video = directorio_workspace / "stream_completo.mp4"
        ruta_chat = directorio_workspace / f"chat_desde_{CHAT_INICIO_SEGUNDOS}.json"
    else:
        ruta_video = directorio_workspace / "stream_completo_speed.mp4"
        ruta_chat = (
            directorio_workspace
            / f"chat_desde_{CHAT_INICIO_SEGUNDOS}_speed.json"
        )

    # Paso 1: Descargar (Omite la descarga si los archivos ya existen para agilizar pruebas)
    if not ruta_video.exists():
        descargar_video(url_stream, str(ruta_video))
    if not os.path.exists(ruta_chat):
        client_id = os.getenv("TWITCH_CLIENT_ID")
        client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RuntimeError(
                "Faltan TWITCH_CLIENT_ID o TWITCH_CLIENT_SECRET. "
                "Añádelos al archivo .env usando .env.example como plantilla."
            )
        descargar_chat(
            url_stream,
            str(ruta_chat),
            client_id,
            client_secret,
            CHAT_INICIO_SEGUNDOS,
            CHAT_FIN_SEGUNDOS,
        )

    # Paso 2: Analizar
    mejores_momentos = analizar_chat(
        str(ruta_chat),
        padding_previo=SEGUNDOS_ANTES_DEL_PICO,
        inicio_analisis=CHAT_INICIO_SEGUNDOS,
        fin_analisis=CHAT_FIN_SEGUNDOS,
        duracion_clip=DURACION_CLIP,
    )
    if not mejores_momentos:
        print("No se encontraron picos virales en este stream.")
        return []

    print(f"Encontrados {len(mejores_momentos)} momentos. Generando el Top {TOP_N_CLIPS}...")

    # Paso 3: Editar y exportar
    clips_generados = []
    for i, clip in enumerate(mejores_momentos[:TOP_N_CLIPS]):
        inicio = clip["inicio"]
        score = clip["score"]
        salida = directorio_workspace / f"clip_top{i+1}_{inicio}s.mp4"
        
        print(f"Procesando Top {i+1} (Inicio: {inicio}s, Score: {score}) -> {salida}")
        crear_clip_pantalla_dividida(
            str(ruta_video),
            inicio,
            DURACION_CLIP,
            coords_camara,
            str(salida),
        )
        clips_generados.append(salida)
        
    print(f"✅ Proceso completado. Revisa la carpeta {directorio_workspace}.")
    return clips_generados


def _argumentos():
    parser = argparse.ArgumentParser(
        description="Descarga un stream y genera clips a partir del chat."
    )
    parser.add_argument(
        "--config",
        help="Ruta al JSON con la URL y las coordenadas de cámara del stream.",
    )
    return parser.parse_args()

if __name__ == "__main__":
    argumentos = _argumentos()
    main(argumentos.config)