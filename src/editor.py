import subprocess

def crear_clip_pantalla_dividida(video_entrada, segundo_inicio, duracion, coords_camara, archivo_salida):
    cx, cy, cw, ch = coords_camara['x'], coords_camara['y'], coords_camara['w'], coords_camara['h']
    
    # 1. Cámara: recorta según coordenadas y escala al ancho del vídeo de salida.
    filtro_camara = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale=1080:-2[camara];"
    
    # 2. Gameplay: recorta el centro del vídeo original a formato cuadrado.
    filtro_gameplay = f"[0:v]crop=1080:1080:(iw-1080)/2:(ih-1080)/2,scale=1080:1080[juego];"
    
    # 3. Apilar
    filtro_apilar = "[camara][juego]vstack=inputs=2[final]"
    filtro_completo = filtro_camara + filtro_gameplay + filtro_apilar

    comando = [
        "ffmpeg", "-y",
        "-ss", str(segundo_inicio),
        "-i", video_entrada,
        "-t", str(duracion),
        "-filter_complex", filtro_completo,
        "-map", "[final]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        archivo_salida
    ]

    resultado = subprocess.run(
        comando,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if resultado.returncode:
        raise RuntimeError(f"FFmpeg no pudo crear {archivo_salida}:\n{resultado.stderr}")