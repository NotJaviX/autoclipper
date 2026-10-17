import argparse

import main as pipeline
from whisper_subtitler import subtitular_video
from youtube_uploader import autenticar_youtube, subir_shorts


def ejecutar_pipeline_con_whisper_youtube(
    modelo_nombre="small",
    idioma=None,
    ruta_config=None,
    client_secrets_path=None,
    title_prefix=None,
):
    try:
        import whisper
    except ImportError as error:
        raise RuntimeError(
            "Falta Whisper en el entorno actual. Instálalo con "
            "'python -m pip install openai-whisper'."
        ) from error

    nombre_perfil, _, _ = pipeline.cargar_configuracion_stream(ruta_config)
    clips = pipeline.main(ruta_config)
    if not clips:
        print("No se generaron clips; se omiten Whisper y la subida.")
        return []

    print(f"Cargando modelo Whisper '{modelo_nombre}'...")
    modelo = whisper.load_model(modelo_nombre)
    clips_subtitulados = []
    for clip in clips:
        video_subtitulado, _ = subtitular_video(
            clip,
            modelo,
            idioma=idioma,
            sobrescribir=True,
        )
        clips_subtitulados.append(video_subtitulado)

    print(
        "Iniciando autorización de YouTube si todavía no hay un token válido. "
        "Las subidas de este flujo serán privadas."
    )
    youtube = autenticar_youtube(client_secrets_path)
    prefijo = title_prefix if title_prefix is not None else nombre_perfil.title()
    return subir_shorts(youtube, clips_subtitulados, prefijo)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta el pipeline, subtitula los clips y los sube a YouTube "
            "como privados."
        )
    )
    parser.add_argument(
        "--config",
        help="Ruta al JSON con la URL y las coordenadas de cámara del stream.",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Modelo Whisper (tiny, base, small, medium o large). Por defecto: small.",
    )
    parser.add_argument(
        "--language",
        help="Idioma hablado, por ejemplo es o en. Si se omite, Whisper lo detecta.",
    )
    parser.add_argument(
        "--client-secrets",
        help=(
            "Ruta al JSON OAuth de Google. Si se omite, usa el único "
            "client_secret_*.json de la raíz."
        ),
    )
    parser.add_argument(
        "--title-prefix",
        help="Texto que se antepone a los títulos automáticos de cada clip.",
    )
    argumentos = parser.parse_args()
    ejecutar_pipeline_con_whisper_youtube(
        modelo_nombre=argumentos.model,
        idioma=argumentos.language,
        ruta_config=argumentos.config,
        client_secrets_path=argumentos.client_secrets,
        title_prefix=argumentos.title_prefix,
    )


if __name__ == "__main__":
    main()
