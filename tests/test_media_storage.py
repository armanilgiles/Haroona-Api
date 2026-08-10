import os
import unittest
from unittest.mock import Mock, patch

from app.media.storage import (
    MediaStorageSettings,
    build_public_media_url,
    create_signed_media_upload,
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
        with self.assertRaises(ValueError):
            create_signed_media_upload(
                storage_key="voice/../secret.m4a",
                mime_type="audio/mp4",
            )


if __name__ == "__main__":
    unittest.main()
