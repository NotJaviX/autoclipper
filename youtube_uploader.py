import json
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TOKEN_PATH = PROJECT_ROOT / ".youtube_token.json"


def _client_secrets_path(client_secrets_path=None):
    if client_secrets_path:
        path = Path(client_secrets_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"No existe el archivo OAuth de Google: {path}")
        return path

    candidates = sorted(PROJECT_ROOT.glob("client_secret_*.json"))
    if len(candidates) != 1:
        raise RuntimeError(
            "Se esperaba exactamente un archivo OAuth client_secret_*.json "
            f"en {PROJECT_ROOT}; encontrados: {len(candidates)}. "
            "Pasa la ruta con --client-secrets."
        )
    return candidates[0]


def autenticar_youtube(client_secrets_path=None, token_path=DEFAULT_TOKEN_PATH):
    client_path = _client_secrets_path(client_secrets_path)
    token_path = Path(token_path)
    credenciales = None

    if token_path.is_file():
        credenciales = Credentials.from_authorized_user_file(
            str(token_path),
            YOUTUBE_UPLOAD_SCOPE,
        )

    if credenciales and credenciales.expired and credenciales.refresh_token:
        credenciales.refresh(Request())
    elif not credenciales or not credenciales.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_path),
            YOUTUBE_UPLOAD_SCOPE,
        )
        credenciales = flow.run_local_server(
            host="localhost",
            port=0,
            access_type="offline",
            prompt="consent",
        )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credenciales.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=credenciales)


def _titulo_limpio(prefijo, clip_path):
    nombre = Path(clip_path).stem.removesuffix("_subtitulado")
    base = re.sub(r"[_-]+", " ", nombre).strip()
    titulo = f"{prefijo} - {base}" if prefijo else base
    return titulo[:100]


def subir_short(youtube, clip_path, title_prefix=None):
    clip_path = Path(clip_path).resolve()
    if not clip_path.is_file():
        raise FileNotFoundError(f"No existe el clip para subir: {clip_path}")
    if not clip_path.stem.endswith("_subtitulado"):
        raise ValueError(
            f"Solo se suben MP4 con subtítulos incrustados: {clip_path.name}"
        )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": _titulo_limpio(title_prefix, clip_path),
                "description": "",
                "categoryId": "20",
            },
            "status": {
                "privacyStatus": "private",
            },
        },
        media_body=MediaFileUpload(
            str(clip_path),
            mimetype="video/mp4",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        ),
    )

    respuesta = None
    while respuesta is None:
        estado, respuesta = request.next_chunk(num_retries=5)
        if estado:
            print(
                f"\rSubiendo {clip_path.name}: "
                f"{estado.progress() * 100:.1f}%",
                end="",
                flush=True,
            )
    print()

    video_id = respuesta.get("id") if isinstance(respuesta, dict) else None
    if not video_id:
        raise RuntimeError(
            f"YouTube terminó la subida de {clip_path.name} "
            "sin devolver un ID de vídeo."
        )
    print(f"Subido como privado: https://www.youtube.com/watch?v={video_id}")
    return video_id


def subir_shorts(youtube, videos, title_prefix=None):
    if not videos:
        print("No hay clips subtitulados para subir.")
        return []

    ids_subidos = []
    for indice, video in enumerate(videos, start=1):
        print(f"Subiendo clip {indice}/{len(videos)}...")
        ids_subidos.append(subir_short(youtube, video, title_prefix))
    return ids_subidos
