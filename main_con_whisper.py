import argparse
from pathlib import Path

import main as pipeline
from whisper_subtitler import subtitular_video


def _directorio_perfil(ruta_config):
    nombre_perfil, _, _ = pipeline.cargar_configuracion_stream(ruta_config)
    return Path("workspace") / nombre_perfil


def _subtitular_clips(clips, modelo, idioma):
    total_subtitulados = 0
    total_sin_voz = 0
    for clip in clips:
        marcador_sin_voz = clip.with_suffix(".no_speech")
        marcador_sin_voz.unlink(missing_ok=True)
        resultado = subtitular_video(
            clip,
            modelo,
            idioma=idioma,
            sobrescribir=True,
        )
        if resultado is None:
            marcador_sin_voz.write_text(
                "Whisper no detectó voz en este clip.\n",
                encoding="utf-8",
            )
            total_sin_voz += 1
        else:
            total_subtitulados += 1
    return total_subtitulados, total_sin_voz


def ejecutar_pipeline_con_whisper(
    modelo_nombre="small",
    idioma=None,
    ruta_config=None,
    reanudar=False,
):
    try:
        import whisper
    except ImportError as error:
        raise RuntimeError(
            "Falta Whisper en el entorno actual. Instálalo con "
            "'python -m pip install openai-whisper'."
        ) from error

    if reanudar:
        directorio = _directorio_perfil(ruta_config)
        if not directorio.is_dir():
            raise FileNotFoundError(
                f"No existe la carpeta del perfil: {directorio}. "
                "Ejecuta primero el pipeline normal para generar los clips."
            )
        clips = sorted(
            clip
            for clip in directorio.glob("clip_top*.mp4")
            if "_subtitulado" not in clip.stem
            and not clip.with_name(f"{clip.stem}_subtitulado.mp4").exists()
            and not clip.with_suffix(".no_speech").exists()
        )
        if not clips:
            print("No quedan clips pendientes de subtitular en este perfil.")
            return
        print(
            f"Reanudando Whisper para {len(clips)} clips pendientes "
            f"en {directorio}."
        )
    else:
        clips = pipeline.main(ruta_config)
    if not clips:
        print("No se generaron clips; se omite la transcripción.")
        return

    print(f"Cargando modelo Whisper '{modelo_nombre}'...")
    modelo = whisper.load_model(modelo_nombre)
    subtitulados, sin_voz = _subtitular_clips(clips, modelo, idioma)
    print(
        f"Proceso completado: {subtitulados} clips subtitulados; "
        f"{sin_voz} clips sin voz marcados y omitidos."
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta el pipeline actual y subtitula sus clips, o reanuda "
            "Whisper sobre los clips ya generados."
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
        "--resume",
        action="store_true",
        help=(
            "No vuelve a descargar ni generar clips; subtitula los clips "
            "pendientes del perfil y omite los ya completados."
        ),
    )
    argumentos = parser.parse_args()
    ejecutar_pipeline_con_whisper(
        argumentos.model,
        argumentos.language,
        argumentos.config,
        argumentos.resume,
    )


if __name__ == "__main__":
    main()
