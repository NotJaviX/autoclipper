import json
import math
import re
from collections import defaultdict

EMOTES_RISA = {"jaja", "jeje", "xd", "lul", "omegalul", "kekw", "💀", "lmao"}
PATRON_HYPE = re.compile(r"\b(?:pogchamp|pog|wtf|dios|locura|ooo|wow|w+)\b", re.IGNORECASE)

def puntuar_mensaje(texto):
    if not texto: return 0
    score = 1.0
    texto = texto.lower()
    if any(emote in texto for emote in EMOTES_RISA): score += 3.0
    if PATRON_HYPE.search(texto): score += 2.0
    return score

def analizar_chat(
    ruta_json,
    window_size=5,
    z_threshold=2.5,
    padding_previo=20,
    inicio_analisis=0,
    fin_analisis=None,
    duracion_clip=20,
):
    print("Analizando picos de chat...")
    with open(ruta_json, 'r', encoding='utf-8') as f:
        datos = json.load(f)

    if isinstance(datos, list):
        mensajes = datos
    elif isinstance(datos, dict) and isinstance(datos.get("comments"), list):
        mensajes = datos["comments"]
    else:
        raise ValueError(
            "Formato de chat no reconocido: se esperaba una lista de mensajes "
            "o un objeto TwitchDownloader con la propiedad 'comments'."
        )
        
    ventanas = defaultdict(float)
    
    for msg in mensajes:
        if not isinstance(msg, dict):
            continue
        segundo_exacto = msg.get("time_in_seconds")
        if segundo_exacto is None:
            segundo_exacto = msg.get("content_offset_seconds")
        if segundo_exacto is None:
            segundo_exacto = msg.get("timestamp")
        if segundo_exacto is None: continue
        texto = msg.get("message", "")
        if isinstance(texto, dict):
            texto = texto.get("body", "")
        if not texto:
            texto = msg.get("content", "")
        if not isinstance(texto, str):
            texto = ""
        if not isinstance(segundo_exacto, (int, float)) or segundo_exacto < 0:
            continue
        if segundo_exacto < inicio_analisis:
            continue
        if fin_analisis is not None and segundo_exacto >= fin_analisis:
            continue
        indice_ventana = (int(segundo_exacto) // window_size) * window_size
        ventanas[indice_ventana] += puntuar_mensaje(texto)

    if not ventanas: return []

    primera_ventana = (inicio_analisis // window_size) * window_size
    ultima_ventana = (
        (int(fin_analisis) - 1) // window_size * window_size
        if fin_analisis is not None
        else max(ventanas)
    )
    puntuaciones = [
        ventanas[tiempo]
        for tiempo in range(primera_ventana, ultima_ventana + window_size, window_size)
    ]
    media = sum(puntuaciones) / len(puntuaciones)
    varianza = sum((x - media) ** 2 for x in puntuaciones) / len(puntuaciones)
    desviacion_estandar = math.sqrt(varianza)
    
    umbral_viral = media + (z_threshold * desviacion_estandar)
    picos_detectados = []
    
    for tiempo in range(primera_ventana, ultima_ventana + window_size, window_size):
        score = ventanas[tiempo]
        if score > umbral_viral:
            inicio_clip = max(inicio_analisis, tiempo - padding_previo)
            picos_detectados.append({
                "timestamp": tiempo,
                "inicio": inicio_clip,
                "score": round(score, 2)
            })

    picos_detectados.sort(key=lambda x: x["timestamp"])
    clips_finales = []
    
    for pico in picos_detectados:
        if not clips_finales:
            clips_finales.append(pico)
        else:
            ultimo = clips_finales[-1]
            if pico["timestamp"] - ultimo["timestamp"] < duracion_clip:
                if pico["score"] > ultimo["score"]:
                    ultimo["score"] = pico["score"]
                    ultimo["inicio"] = pico["inicio"]
            else:
                clips_finales.append(pico)

    clips_finales.sort(key=lambda x: x["score"], reverse=True)
    return clips_finales