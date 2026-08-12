import os
import unittest
from uuid import UUID
from unittest.mock import Mock, patch

from app.media.audio import (
    MAX_VOICE_RECORDING_DURATION_SECONDS,
    MAX_VOICE_RECORDING_FILE_SIZE_BYTES,
    generate_voice_storage_key,
    normalize_audio_mime_type,
)
from app.media.storage import (
    MediaObjectMetadata,
    MediaStorageSettings,
    build_public_media_url,
    create_signed_media_download,
    create_signed_media_upload,
    delete_media_object,
    get_media_object_metadata,
)


class MediaStorageTests(unittest.TestCase):
    def test_signed_upload_uses_configured_bucket_and_content_type(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://uploads.example.test/signed"

        with patch.dict(
            os.environ,
            {
                "HAROONA_MEDIA_BUCKET": "haroona-media",
                "HAROONA_MEDIA_REGION": "us-east-1",
            },
            clear=True,
        ), patch("app.media.storage.build_media_storage_client", return_value=client):
            upload = create_signed_media_upload(
                storage_key="voice/user-7/session-9.m4a",
                mime_type="audio/mp4",
                expires_in_seconds=600,
            )

        self.assertEqual(upload.method, "PUT")
        self.assertEqual(upload.headers, {"Content-Type": "audio/mp4"})
        self.assertEqual(upload.expires_in_seconds, 600)
        client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "haroona-media",
                "Key": "voice/user-7/session-9.m4a",
                "ContentType": "audio/mp4",
            },
            ExpiresIn=600,
        )

    def test_signed_upload_requires_server_metadata_headers(self):
        client = Mock()
        client.generate_presigned_url.return_value = "https://uploads.example.test/signed"

        with patch.dict(
            os.environ,
            {"HAROONA_MEDIA_BUCKET": "haroona-media"},
            clear=True,
        ), patch("app.media.storage.build_media_storage_client", return_value=client):
            upload = create_signed_media_upload(
                storage_key="voice/user-7/session-9.webm",
                mime_type="audio/webm",
                metadata={
                    "voice-reaction-id": "27",
                    "duration-ms": "12000",
                },
            )

        self.assertEqual(
            upload.headers,
            {
                "Content-Type": "audio/webm",
                "x-amz-meta-voice-reaction-id": "27",
                "x-amz-meta-duration-ms": "12000",
            },
        )
        client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "haroona-media",
                "Key": "voice/user-7/session-9.webm",
                "ContentType": "audio/webm",
                "Metadata": {
                    "voice-reaction-id": "27",
                    "duration-ms": "12000",
                },
            },
            ExpiresIn=900,
        )

    def test_head_download_and_delete_use_the_configured_private_object(self):
        client = Mock()
        client.head_object.return_value = {
            "ContentLength": 4096,
            "ContentType": "audio/webm",
            "Metadata": {
                "voice-reaction-id": "27",
                "duration-ms": "12000",
            },
        }
        client.generate_presigned_url.return_value = (
            "https://media.example.test/signed-playback"
        )

        with patch.dict(
            os.environ,
            {"HAROONA_MEDIA_BUCKET": "haroona-media"},
            clear=True,
        ), patch("app.media.storage.build_media_storage_client", return_value=client):
            metadata = get_media_object_metadata(
                storage_key="voice/user-7/session-9.webm"
            )
            download = create_signed_media_download(
                storage_key="voice/user-7/session-9.webm",
                mime_type="audio/webm",
                expires_in_seconds=300,
            )
            delete_media_object(storage_key="voice/user-7/session-9.webm")

        self.assertEqual(
            metadata,
            MediaObjectMetadata(
                content_length=4096,
                content_type="audio/webm",
                metadata={
                    "voice-reaction-id": "27",
                    "duration-ms": "12000",
                },
            ),
        )
        self.assertEqual(download.url, "https://media.example.test/signed-playback")
        client.head_object.assert_called_once_with(
            Bucket="haroona-media",
            Key="voice/user-7/session-9.webm",
        )
        client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "haroona-media",
                "Key": "voice/user-7/session-9.webm",
                "ResponseContentType": "audio/webm",
            },
            ExpiresIn=300,
        )
        client.delete_object.assert_called_once_with(
            Bucket="haroona-media",
            Key="voice/user-7/session-9.webm",
        )

    def test_public_url_encodes_each_object_key_segment(self):
        settings = MediaStorageSettings(
            bucket="haroona-media",
            public_base_url="https://cdn.example.test/media",
            endpoint_url=None,
            region="us-east-1",
            access_key_id=None,
            secret_access_key=None,
        )

        self.assertEqual(
            build_public_media_url(settings, "voice/user 7/take #1.m4a"),
            "https://cdn.example.test/media/voice/user%207/take%20%231.m4a",
        )

    def test_signed_upload_rejects_unsafe_storage_keys(self):
        unsafe_keys = (
            "voice/../secret.m4a",
            "/voice/user/take.m4a",
            "voice//take.m4a",
            "voice\\user\\take.m4a",
        )

        for storage_key in unsafe_keys:
            with self.subTest(storage_key=storage_key), self.assertRaises(ValueError):
                create_signed_media_upload(
                    storage_key=storage_key,
                    mime_type="audio/mp4",
                )

    def test_voice_key_generation_is_opaque_safe_and_mime_aware(self):
        object_id = UUID("12345678-1234-5678-1234-567812345678")

        key = generate_voice_storage_key(
            user_id="../creator@example.test",
            mime_type="audio/webm; codecs=opus",
            unique_id=object_id,
        )

        self.assertRegex(
            key,
            r"^voice/[a-f0-9]{24}/12345678123456781234567812345678\.webm$",
        )
        self.assertNotIn("creator", key)
        self.assertNotIn("..", key)

    def test_voice_mime_policy_and_limits_are_centralized(self):
        self.assertEqual(normalize_audio_mime_type(" Audio/MP4 "), "audio/mp4")
        self.assertEqual(MAX_VOICE_RECORDING_DURATION_SECONDS, 90)
        self.assertEqual(MAX_VOICE_RECORDING_FILE_SIZE_BYTES, 10 * 1024 * 1024)

        with self.assertRaises(ValueError):
            normalize_audio_mime_type("audio/wav")


if __name__ == "__main__":
    unittest.main()
