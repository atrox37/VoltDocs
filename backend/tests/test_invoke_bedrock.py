import asyncio
from unittest.mock import MagicMock, patch

from services.bedrock import invoke_bedrock_text


def test_invoke_bedrock_text_passes_keyword_args() -> None:
    async def run() -> str:
        with patch("services.bedrock._build_client") as mock_client:
            mock_client.return_value.converse.return_value = {
                "output": {"message": {"content": [{"text": "ok"}]}}
            }
            with patch("services.bedrock._converse_sync", return_value="ok") as mock_sync:
                result = await invoke_bedrock_text(
                    system_prompt="sys",
                    user_message="user",
                    model_id="test-model",
                    region="us-east-1",
                    max_tokens=1024,
                    temperature=0.1,
                )
                assert result == "ok"
                mock_sync.assert_called_once()
                _, kwargs = mock_sync.call_args
                assert kwargs["max_tokens"] == 1024
                assert kwargs["temperature"] == 0.1

    asyncio.run(run())
