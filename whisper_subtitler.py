import argparse
import json
import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

MAX_PALABRAS_SUBTITULO = 3
DURACION_MAX_SUBTITULO = 1.5


def _srt_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def _ass_time(seconds):
    centiseconds = round(seconds * 100)
    hours, centiseconds = divmod(centiseconds, 360_000)
    minutes, centiseconds = divmod(centiseconds, 6_000)
    seconds, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def _subtitle_text(text):
    safe_text = text.strip().replace("\\", "\\\\").replace("{", "(").replace("}", ")")
    return textwrap.fill(safe_text, width=42).replace("\n", r"\N")


def _caption_entries(segments):
    words = []
    for segment in segments:
        timed_words = segment.get("words")
        if isinstance(timed_words, list) and timed_words:
            for word in timed_words:
                text = word.get("word", "").strip()
                start = word.get("start")
                end = word.get("end")
                if (
                    text
                    and isinstance(start, (int, float))
                    and isinstance(end, (int, float))
                    and end > start
                ):
                    words.append((start, end, text))
            continue

        text = segment.get("text", "").strip()
        start = segment.get("start")
        end = segment.get("end")
        if not text or not isinstance(start, (int, float)) or not isinstance(
            end, (int, float)
        ):
            continue
        tokens = text.split()
        if not tokens or end <= start:
            continue
        weights = [len(token) for token in tokens]
        total_weight = sum(weights)
        current = start
        for token, weight in zip(tokens, weights):
            token_end = current + (end - start) * weight / total_weight
            words.append((current, token_end, token))
            current = token_end

    words.sort(key=lambda word: word[0])
    entries = []
    current_words = []
    current_start = None
    current_end = None
    for start, end, text in words:
        if current_words and (
            len(current_words) >= MAX_PALABRAS_SUBTITULO
            or end - current_start > DURACION_MAX_SUBTITULO
            or re.search(r"[.!?…][\"')\]]*$", current_words[-1])
        ):
            entries.append((current_start, current_end, " ".join(current_words)))
            current_words = []
            current_start = None

        if current_start is None:
            current_start = start
        current_words.append(text)
        current_end = end

    if current_words:
        entries.append((current_start, current_end, " ".join(current_words)))
    return entries


def _write_srt(entries, output_path):
    if not entries:
        raise ValueError("Whisper no devolvió segmentos de subtítulos utilizables.")

    output_path.write_text(
        "\n\n".join(
            f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}"
            for index, (start, end, text) in enumerate(entries, start=1)
        )
        + "\n",
        encoding="utf-8",
    )
    return entries


def _write_ass(entries, output_path, width, height, split_y):
    header = f"""[Script Info]
Title: AutoClipper subtitles
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,62,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,1,4,2,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = [
        f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{{\\an5\\pos({width // 2},{split_y})\\q2}}{_subtitle_text(text)}"
        for start, end, text in entries
    ]
    output_path.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")


def _video_dimensions(video_path):
    resultado = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    streams = json.loads(resultado.stdout).get("streams", [])
    if not streams:
        raise ValueError(f"No se pudo leer la resolución del vídeo: {video_path}")
    return streams[0]["width"], streams[0]["height"]


def subtitular_video(video_path, modelo, idioma=None, sobrescribir=False):
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"No existe el vídeo de entrada: {video_path}")

    salida_video = video_path.with_name(f"{video_path.stem}_subtitulado.mp4")
    salida_srt = video_path.with_name(f"{video_path.stem}_subtitulado.srt")
    if not sobrescribir and (salida_video.exists() or salida_srt.exists()):
        raise FileExistsError(
            f"Ya existe una salida subtitulada para {video_path.name}; "
            "usa --overwrite para reemplazarla."
        )

    width, height = _video_dimensions(video_path)
    split_y = max(0, height - width)
    print(f"Transcribiendo {video_path.name} con Whisper...")
    resultado = modelo.transcribe(
        str(video_path),
        language=idioma,
        word_timestamps=True,
        verbose=False,
    )
    segmentos = resultado.get("segments")
    if not isinstance(segmentos, list):
        raise ValueError("Whisper devolvió un resultado sin segmentos de transcripción.")

    entradas = _caption_entries(segmentos)
    if not entradas:
        if sobrescribir:
            salida_video.unlink(missing_ok=True)
            salida_srt.unlink(missing_ok=True)
        print(f"Sin voz reconocible en {video_path.name}; no se generan subtítulos.")
        return None

    _write_srt(entradas, salida_srt)
    with tempfile.TemporaryDirectory(prefix="autoclipper_subs_") as directorio_temporal:
        archivo_ass = Path(directorio_temporal) / "captions.ass"
        _write_ass(entradas, archivo_ass, width, height, split_y)
        comando = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "subtitles=captions.ass",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map_metadata",
            "0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(salida_video),
        ]
        try:
            subprocess.run(
                comando,
                cwd=directorio_temporal,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"FFmpeg no pudo subtitular {video_path.name}:\n{error.stderr}"
            ) from error

    print(f"Vídeo subtitulado: {salida_video}")
    print(f"Subtítulos SRT: {salida_srt}")
    print(
        f"Subtítulos centrados en la división ({width // 2}, {split_y}), "
        f"con hasta {MAX_PALABRAS_SUBTITULO} palabras por bloque."
    )
    return salida_video, salida_srt


def _buscar_videos(ruta):
    if ruta.is_file():
        return [ruta]
    if not ruta.is_dir():
        raise FileNotFoundError(f"No existe la ruta de entrada: {ruta}")
    videos = sorted(
        video
        for video in ruta.glob("clip_top*.mp4")
        if "_subtitulado" not in video.stem
    )
    if not videos:
        raise FileNotFoundError(
            f"No se encontraron archivos clip_top*.mp4 en {ruta}."
        )
    return videos


def main():
    parser = argparse.ArgumentParser(
        description="Genera subtítulos con Whisper para uno o varios clips existentes."
    )
    parser.add_argument(
        "entrada",
        type=Path,
        help="Ruta de un MP4 o carpeta con clips clip_top*.mp4.",
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
        "--overwrite",
        action="store_true",
        help="Reemplaza los archivos subtitulados existentes.",
    )
    argumentos = parser.parse_args()

    try:
        import whisper
    except ImportError as error:
        raise SystemExit(
            "Falta Whisper. Instálalo en el entorno virtual con "
            "'python -m pip install openai-whisper'."
        ) from error

    videos = _buscar_videos(argumentos.entrada.resolve())
    print(f"Cargando modelo Whisper '{argumentos.model}'...")
    modelo = whisper.load_model(argumentos.model)
    for video in videos:
        subtitular_video(
            video,
            modelo,
            idioma=argumentos.language,
            sobrescribir=argumentos.overwrite,
        )


if __name__ == "__main__":
    main()
