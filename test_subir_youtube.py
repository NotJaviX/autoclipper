from pathlib import Path

from youtube_uploader import autenticar_youtube, subir_short


def main():
    ruta_video = input(
        "Ruta del MP4 subtitulado que quieres subir "
        "(por ejemplo workspace\\speed\\clip_subtitulado.mp4): "
    ).strip().strip('"')
    if not ruta_video:
        raise ValueError("Debes indicar la ruta del vídeo.")

    video = Path(ruta_video).expanduser()
    if not video.is_file():
        raise FileNotFoundError(f"No existe el vídeo: {video}")
    if video.suffix.lower() != ".mp4":
        raise ValueError("El vídeo de prueba debe ser un archivo MP4.")
    if not video.stem.endswith("_subtitulado"):
        raise ValueError(
            "El cargador actual solo permite subir clips subtitulados. "
            "El archivo debe terminar en '_subtitulado.mp4'."
        )

    prefijo = input("Prefijo del título (Enter para 'Prueba'): ").strip()
    prefijo = prefijo or "Prueba"

    print(f"\nArchivo: {video.resolve()}")
    print(f"Visibilidad: privado")
    confirmacion = input("Se subirá a YouTube como privado. Escribe SUBIR para continuar: ")
    if confirmacion.strip() != "SUBIR":
        print("Subida cancelada; no se contactó con YouTube.")
        return

    youtube = autenticar_youtube()
    video_id = subir_short(youtube, video, prefijo)
    print(f"Prueba completada. ID del vídeo: {video_id}")


if __name__ == "__main__":
    main()
