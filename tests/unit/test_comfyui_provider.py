"""ComfyUIProvider の単体テスト"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ============================================================
# Health check tests
# ============================================================


@pytest.mark.asyncio
async def test_health_check_returns_true_when_comfyui_responds():
    """ComfyUIが200を返すとhealth_checkがTrue"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template="dummy.json")
        result = await provider.health_check()

        assert result is True
        mock_client.get.assert_called_once_with(
            "http://localhost:8188/system_stats",
            timeout=httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0),
        )


@pytest.mark.asyncio
async def test_health_check_returns_false_on_connection_error():
    """ComfyUIに接続できないとhealth_checkがFalse"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template="dummy.json")
        result = await provider.health_check()

        assert result is False


@pytest.mark.asyncio
async def test_health_check_returns_false_on_non_200():
    """ComfyUIが200以外を返すとhealth_checkがFalse"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template="dummy.json")
        result = await provider.health_check()

        assert result is False


# ============================================================
# Generate tests
# ============================================================


@pytest.mark.asyncio
async def test_generate_submits_workflow_and_returns_images(tmp_path):
    """generateがworkflowを送信し、ポーリングして画像を返す"""
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps({"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "NOUS:prompt"}}})
    )
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        # POST /prompt レスポンス
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "test-id-123"}

        # GET /history/test-id-123 — 初回は空、2回目で完了
        empty_hist = MagicMock()
        empty_hist.json.return_value = {}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "test-id-123": {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "nous_comfyui_0001.png", "type": "output"},
                        ],
                    },
                },
            },
        }

        # GET /view — 画像ダウンロード
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[empty_hist, completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cute cat", size="512x512", n=1)

        assert len(images) == 1
        assert images[0].size == "512x512"
        assert images[0].revised_prompt == "a cute cat"
        assert len(images[0].base64) > 0
        assert images[0].display is True

        # POST /prompt が正しく呼ばれたことを確認
        post_call = mock_client.post.call_args
        assert post_call[0][0] == "http://localhost:8188/prompt"
        sent_workflow = post_call[1]["json"]["prompt"]
        assert sent_workflow["6"]["inputs"]["text"] == "a cute cat"


@pytest.mark.asyncio
async def test_generate_retries_on_connection_error(tmp_path):
    """generateが接続エラー時にリトライする"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "test-id-456"}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "test-id-456": {
                "outputs": {
                    "9": {
                        "images": [{"filename": "out.png", "type": "output"}],
                    },
                },
            },
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(side_effect=[httpx.ConnectError("fail"), httpx.ConnectError("fail"), post_resp])
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await provider.generate(prompt="test", n=1)

        assert mock_client.post.call_count == 3  # 初回 + 2リトライ


@pytest.mark.asyncio
async def test_generate_raises_on_all_retries_fail(tmp_path):
    """全リトライが失敗すると例外が上がる"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))

        with pytest.raises(RuntimeError, match="ComfyUI generation failed after retries"):
            await provider.generate(prompt="test", n=1)

        assert mock_client.post.call_count == 3


@pytest.mark.asyncio
async def test_generate_times_out_after_timeout_seconds(tmp_path):
    """timeout_seconds を超えると実時間でタイムアウトする（sleep モックなし）"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "timeout-id"}

        # 常に空の履歴を返す
        empty_hist = MagicMock()
        empty_hist.json.return_value = {}

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(return_value=empty_hist)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188",
            workflow_template=str(template),
            timeout_seconds=1.0,
        )

        start = time.monotonic()
        with pytest.raises(RuntimeError, match="ComfyUI generation timed out after 1s"):
            await provider.generate(prompt="test", n=1)
        elapsed = time.monotonic() - start

        # sleep モックに依存せず実時間でタイムアウトしていること
        assert elapsed >= 1.0


@pytest.mark.asyncio
async def test_generate_raises_immediately_on_comfyui_error_status(tmp_path):
    """history の status_str == "error" で即 RuntimeError（ポーリング継続しない）"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "error-id"}

        error_hist = MagicMock()
        error_hist.json.return_value = {
            "error-id": {
                "status": {
                    "status_str": "error",
                    "messages": [["execution_error", {"exception_message": "CUDA OOM"}]],
                },
                "outputs": {},
            }
        }

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(return_value=error_hist)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            pytest.raises(RuntimeError, match="ComfyUI generation failed: .*CUDA OOM"),
        ):
            await provider.generate(prompt="test", n=1)

        # 1回のポーリングで即失敗（タイムアウトまで回さない）
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_generate_raises_plain_error_without_messages(tmp_path):
    """status に messages が無い場合はシンプルなエラーメッセージで即失敗"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "error-id2"}

        error_hist = MagicMock()
        error_hist.json.return_value = {
            "error-id2": {
                "status": {"status_str": "error"},  # messages 無し
                "outputs": {},
            }
        }

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(return_value=error_hist)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            pytest.raises(RuntimeError, match="^ComfyUI generation failed$"),
        ):
            await provider.generate(prompt="test", n=1)

        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_generate_multiple_images(tmp_path):
    """n>1で複数枚生成できる"""
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"1": {"class_type": "KSampler", "inputs": {"seed": 1}}}))
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "multi-id"}

        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "multi-id": {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "nous_comfyui_0001.png", "type": "output"},
                            {"filename": "nous_comfyui_0002.png", "type": "output"},
                        ],
                    },
                },
            },
        }

        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"fake_png_data"

        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="test", n=2)

        assert len(images) == 2


# ============================================================
# Workflow build tests
# ============================================================


def test_workflow_template_required():
    """workflow_template が空なら構築時に ValueError"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    with pytest.raises(ValueError, match="workflow_template"):
        ComfyUIProvider(api_url="http://localhost:8188", workflow_template="")


def test_provider_name():
    """provider_nameがcomfyuiを返す"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    assert provider.provider_name == "comfyui"


def test_timeout_seconds_default_is_180():
    """timeout_seconds 未指定時はデフォルト 180 秒"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    assert provider._timeout_seconds == 180.0


def test_client_timeout_follows_timeout_seconds():
    """client の read/write タイムアウトが timeout_seconds に連動する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", timeout_seconds=77.0)
    with patch("httpx.AsyncClient") as mock_client_class:
        _ = provider.client
    timeout = mock_client_class.call_args.kwargs["timeout"]
    assert timeout.read == 77.0
    assert timeout.write == 77.0
    assert timeout.connect == 5.0
    assert timeout.pool == 5.0


def test_tool_config_comfyui_timeout_default_is_180():
    """ToolConfig の image_gen_comfyui_timeout_seconds デフォルトは 180"""
    from nous.domain.tool_config import ToolConfig

    assert ToolConfig().image_gen_comfyui_timeout_seconds == 180


def test_tool_config_workflow_source_defaults():
    """新フィールドのデフォルトは local + 空名（後方互換）。"""
    from nous.domain.tool_config import ToolConfig

    config = ToolConfig()
    assert config.image_gen_comfyui_workflow_source == "local"
    assert config.image_gen_comfyui_workflow_name == ""


def test_tool_config_removed_params_absent():
    """廃止フィールド（checkpoint/loras/steps/cfg/sampler/scheduler/denoise/seed）が無いこと。"""
    from nous.domain.tool_config import ToolConfig

    config = ToolConfig()
    for field in (
        "image_gen_comfyui_checkpoint",
        "image_gen_comfyui_loras",
        "image_gen_comfyui_steps",
        "image_gen_comfyui_cfg",
        "image_gen_comfyui_sampler",
        "image_gen_comfyui_scheduler",
        "image_gen_comfyui_denoise",
        "image_gen_comfyui_seed",
    ):
        assert not hasattr(config, field), f"{field} は廃止されているべき"
    # サイズ系は維持
    assert config.image_gen_comfyui_width == 1024
    assert config.image_gen_comfyui_height == 1024


# ============================================================
# NOUS tag injection tests (template mode)
# ============================================================


def test_nous_negative_prompt_empty_passthrough():
    """NOUS:negative_prompt は空なら空のまま（デフォルト値は使わない）"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {}, "_meta": {"title": "NOUS:negative_prompt"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", seed=1)
    assert workflow["1"]["inputs"]["text"] == ""


def test_nous_no_tags_leaves_workflow_unchanged():
    """NOUS:タグが無ければワークフローは変更されない"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {
        "1": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 512}},
    }
    result = provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", seed=1)
    assert result is workflow
    assert workflow["1"]["inputs"] == {"seed": 1}


@pytest.mark.asyncio
async def test_generate_template_mode_injects_nous_tags(tmp_path):
    """テンプレートモードで NOUS:タグが注入されて送信される"""
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": 0,
                        "steps": 5,
                        "cfg": 1.0,
                        "sampler_name": "x",
                        "scheduler": "y",
                        "denoise": 1.0,
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["5", 0],
                    },
                    "_meta": {"title": "NOUS:seed"},
                },
                "5": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": 512, "height": 512, "batch_size": 1},
                    "_meta": {"title": "NOUS:width"},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "x"},
                    "_meta": {"title": "NOUS:prompt"},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "x"},
                    "_meta": {"title": "NOUS:negative_prompt"},
                },
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0]}},
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"filename_prefix": "x", "images": ["8", 0]},
                    "_meta": {"title": "main_out"},
                },
            },
            ensure_ascii=False,
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "nous-id"}
        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "nous-id": {"outputs": {"9": {"images": [{"filename": "o.png", "type": "output"}]}}}
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"png"
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188",
            workflow_template=str(template),
            width=1024,
            height=2048,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cat", n=1)

        sent = mock_client.post.call_args[1]["json"]["prompt"]
        # seed は毎回ランダム化される（apply_generation_params が固定 seed を上書き）
        assert isinstance(sent["3"]["inputs"]["seed"], int)
        assert 1 <= sent["3"]["inputs"]["seed"] < 2**63
        assert sent["5"]["inputs"]["width"] == 1024
        assert sent["6"]["inputs"]["text"] == "a cat"
        assert sent["7"]["inputs"]["text"] == ""

        # 出力ノードの node_id / node_title が付与される
        assert len(images) == 1
        assert images[0].node_id == "9"
        assert images[0].node_title == "main_out"
        # NOUS:display タグ無し → 全画像 display=True
        assert images[0].display is True


@pytest.mark.asyncio
async def test_generate_template_mode_legacy_placeholders(tmp_path):
    """レガシー {{placeholder}} 置換が引き続き動作する"""
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "model": ["4", 0]}},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{width}}", "height": "{{height}}"}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{negative_prompt}}"}},
            },
            ensure_ascii=False,
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "legacy-id"}
        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "legacy-id": {"outputs": {"9": {"images": [{"filename": "o.png", "type": "output"}]}}}
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"png"
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188",
            workflow_template=str(template),
            width=768,
            height=640,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await provider.generate(prompt="hello", n=1)

        sent = mock_client.post.call_args[1]["json"]["prompt"]
        # {{seed}} は毎回ランダムな int に置換される（ワークフロー保存時の固定 seed 対策）
        assert int(sent["3"]["inputs"]["seed"]) >= 1
        assert sent["5"]["inputs"]["width"] == "768"
        assert sent["5"]["inputs"]["height"] == "640"
        assert sent["6"]["inputs"]["text"] == "hello"
        assert sent["7"]["inputs"]["text"] == ""


# ============================================================
# Node info attachment tests (node_id / node_title)
# ============================================================


class _FakeResp:
    """テスト用の最小レスポンス (json/content/raise_for_status)"""

    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def content(self):
        return self._payload


def test_generated_image_node_fields_default_to_none():
    """GeneratedImage の node_id/node_title はデフォルト None"""
    from nous.infrastructure.image_gen.base import GeneratedImage

    img = GeneratedImage(base64="xxx", revised_prompt="p", size="512x512")
    assert img.node_id is None
    assert img.node_title is None


@pytest.mark.asyncio
async def test_poll_result_sets_node_id_and_title():
    """_poll_result が履歴の node_id と node_titles から node_id/node_title を設定する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", api_url="http://localhost:8188")
    hist = _FakeResp(
        {
            "pid": {
                "outputs": {
                    "9": {"images": [{"filename": "a.png", "type": "output"}]},
                    "10": {"images": [{"filename": "b.png", "type": "output"}]},
                }
            }
        }
    )
    img_resp = _FakeResp(b"png")
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[hist, img_resp, img_resp])
    provider._client = fake_client

    images = await provider._poll_result(
        "pid", prompt="cat", size="512x512", n=4, node_titles={"9": "main", "10": "upscale"}
    )
    assert len(images) == 2
    assert images[0].node_id == "9"
    assert images[0].node_title == "main"
    assert images[1].node_id == "10"
    assert images[1].node_title == "upscale"
    assert images[0].revised_prompt == "cat"
    assert images[0].base64


@pytest.mark.asyncio
async def test_poll_result_node_title_none_when_not_in_map():
    """node_titles に無い node_id の node_title は None"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", api_url="http://localhost:8188")
    hist = _FakeResp({"pid": {"outputs": {"9": {"images": [{"filename": "a.png", "type": "output"}]}}}})
    img_resp = _FakeResp(b"png")
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[hist, img_resp])
    provider._client = fake_client

    images = await provider._poll_result("pid", prompt="cat", size="512x512", n=1, node_titles={"10": "upscale"})
    assert images[0].node_id == "9"
    assert images[0].node_title is None


def test_sanitize_node_title():
    """_sanitize_node_title がファイル名に使える形に整形する"""
    from nous.application.chat.tools.builtin import _sanitize_node_title

    assert _sanitize_node_title(None) == ""
    assert _sanitize_node_title("") == ""
    assert _sanitize_node_title("   ") == ""
    assert _sanitize_node_title("Main Output!") == "Main_Output"
    assert _sanitize_node_title("already-snake_case") == "already-snake_case"
    assert len(_sanitize_node_title("x" * 100)) == 32


# ============================================================
# NOUS:display node filtering tests
# ============================================================


@pytest.mark.asyncio
async def test_generate_template_mode_display_filters_outputs(tmp_path):
    """NOUS:display タグ付きノードの出力のみ display=True になる（前後空白も許容）"""
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["4", 0]}},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
                "9": {
                    "class_type": "SaveImage",
                    "inputs": {"images": ["3", 0]},
                    "_meta": {"title": " NOUS:display "},
                },
                "10": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
            },
            ensure_ascii=False,
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "disp-id"}
        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "disp-id": {
                "outputs": {
                    "9": {"images": [{"filename": "a.png", "type": "output"}]},
                    "10": {"images": [{"filename": "b.png", "type": "output"}]},
                }
            }
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"png"
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cat", n=4)

        assert len(images) == 2
        assert images[0].node_id == "9"
        assert images[0].display is True
        assert images[1].node_id == "10"
        assert images[1].display is False


@pytest.mark.asyncio
async def test_generate_template_mode_display_title_prefix_not_matched(tmp_path):
    """NOUS:display 以外の NOUS: タグ付きノードは表示フィルタ対象にならない"""
    template = tmp_path / "template.json"
    template.write_text(
        json.dumps(
            {
                "3": {"class_type": "KSampler", "inputs": {"seed": 1, "model": ["4", 0]}},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
                "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}, "_meta": {"title": "NOUS:displayx"}},
            },
            ensure_ascii=False,
        )
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "disp-id2"}
        completed_hist = MagicMock()
        completed_hist.json.return_value = {
            "disp-id2": {"outputs": {"9": {"images": [{"filename": "a.png", "type": "output"}]}}}
        }
        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"png"
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client.get = AsyncMock(side_effect=[completed_hist, img_resp])
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template=str(template))
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cat", n=1)

        assert len(images) == 1
        assert images[0].display is True


@pytest.mark.asyncio
async def test_poll_result_display_none_means_all_true():
    """display_node_ids=None → 全画像 display=True（後方互換）"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", api_url="http://localhost:8188")
    hist = _FakeResp({"pid": {"outputs": {"9": {"images": [{"filename": "a.png", "type": "output"}]}}}})
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[hist, _FakeResp(b"png")])
    provider._client = fake_client

    images = await provider._poll_result("pid", prompt="c", size="512x512", n=1)
    assert images[0].display is True


@pytest.mark.asyncio
async def test_poll_result_display_filters_by_node_ids():
    """display_node_ids に含まれないノード出力は display=False"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", api_url="http://localhost:8188")
    hist = _FakeResp(
        {
            "pid": {
                "outputs": {
                    "9": {"images": [{"filename": "a.png", "type": "output"}]},
                    "10": {"images": [{"filename": "b.png", "type": "output"}]},
                }
            }
        }
    )
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[hist, _FakeResp(b"png"), _FakeResp(b"png")])
    provider._client = fake_client

    images = await provider._poll_result("pid", prompt="c", size="512x512", n=4, display_node_ids={"9"})
    assert images[0].display is True
    assert images[1].display is False


@pytest.mark.asyncio
async def test_poll_result_display_no_match_falls_back_all(caplog):
    """display_node_ids が出力ノードと一致しない場合は全表示にフォールバックして警告"""
    import logging

    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    caplog.set_level(logging.WARNING)
    provider = ComfyUIProvider(workflow_template="dummy.json", api_url="http://localhost:8188")
    hist = _FakeResp({"pid": {"outputs": {"9": {"images": [{"filename": "a.png", "type": "output"}]}}}})
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=[hist, _FakeResp(b"png")])
    provider._client = fake_client

    images = await provider._poll_result("pid", prompt="c", size="512x512", n=1, display_node_ids={"99"})
    assert images[0].display is True
    assert "NOUS:display" in caplog.text


@pytest.mark.asyncio
async def test_builtin_image_generate_skips_non_display_images(tmp_path, monkeypatch):
    """display=False の画像は保存もレスポンスにも含まれない"""
    from nous.application.chat.tools.builtin import _handle_image_generate
    from nous.infrastructure.image_gen.base import GeneratedImage

    ctx = MagicMock()
    ctx.persona = "test_persona"
    ctx.event_bus = AsyncMock()

    config = MagicMock()
    config.image_gen_enabled = True
    config.image_gen_presets = {}
    config.image_gen_default_preset = "square_medium"
    config.image_gen_max_width = 1200
    config.image_gen_max_height = 1200
    config.image_gen_negative_prompt = ""
    config.image_gen_comfyui_url = "http://localhost:8188"

    settings = MagicMock()
    settings.data_root = str(tmp_path)
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: settings)

    generated = [
        GeneratedImage(base64="aGVsbG8=", revised_prompt="p", size="768x768", display=True),
        GeneratedImage(base64="d29ybGQ=", revised_prompt="p", size="768x768", display=False),
        GeneratedImage(base64="IQ==", revised_prompt="p", size="768x768", display=True),
    ]
    fake_provider = MagicMock()
    fake_provider.generate = AsyncMock(return_value=generated)
    monkeypatch.setattr("nous.infrastructure.image_gen.comfyui.ComfyUIProvider", lambda **kw: fake_provider)

    result = await _handle_image_generate(ctx, config, {"prompt": "a cat"})

    assert result["status"] == "success"
    assert len(result["images"]) == 2
    assert result["images"][0]["base64"] == "aGVsbG8="
    assert result["images"][1]["base64"] == "IQ=="
    saved = sorted(p for p in (tmp_path / "persona" / "test_persona" / "images").glob("*.png"))
    assert len(saved) == 2
    assert saved[0].name.endswith("_00.png")
    assert saved[1].name.endswith("_01.png")


# ============================================================
# 実行時パラメータ適用（apply_generation_params 統合）
# ============================================================


@pytest.mark.asyncio
async def test_generate_injects_size_batch_and_random_seed():
    """workflow_source='comfyui': 変換後にサイズ・枚数・ランダムシードが適用される。"""
    import json as _json

    from tests.unit.workflow_fixtures import MINI_UI_WORKFLOW, OBJECT_INFO

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()

        userdata_resp = MagicMock()
        userdata_resp.status_code = 200
        userdata_resp.text = _json.dumps(MINI_UI_WORKFLOW)

        object_info_resp = MagicMock()
        object_info_resp.status_code = 200
        object_info_resp.json.return_value = OBJECT_INFO

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"prompt_id": "pid-1"}

        hist_resp = MagicMock()
        hist_resp.json.return_value = {
            "pid-1": {
                "outputs": {
                    "13": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]}
                }
            }
        }

        img_resp = MagicMock()
        img_resp.status_code = 200
        img_resp.content = b"pngdata"

        mock_client.get = AsyncMock(side_effect=[userdata_resp, object_info_resp, hist_resp, img_resp, img_resp])
        mock_client.post = AsyncMock(return_value=post_resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188",
            workflow_source="comfyui",
            workflow_name="Anima_T2I_Turbo_Aesthetic.json",
            width=896,
            height=1152,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="The Herta, dancing", size="896x1152", n=2)

        assert len(images) == 2
        post_call = mock_client.post.call_args
        sent = post_call[1]["json"]["prompt"]
        # 固定 seed 875817230929465 がランダム化されている（MINI_UI_WORKFLOW の KSampler は固定 seed）
        assert sent["9"]["inputs"]["seed"] != 875817230929465
        assert 1 <= sent["9"]["inputs"]["seed"] < 2**63
        # NOUS:prompt タグ注入は従来どおり
        assert sent["6"]["inputs"]["text"] == "The Herta, dancing"


@pytest.mark.asyncio
async def test_nous_injects_remaining_keys():
    """残存タグ（prompt / negative_prompt / width / height / seed）だけが注入される。"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_template="dummy.json")
    workflow = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "NOUS:prompt"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}, "_meta": {"title": "NOUS:negative_prompt"}},
        "3": {"class_type": "INTConstant", "inputs": {"value": 0}, "_meta": {"title": "NOUS:width"}},
        "4": {"class_type": "INTConstant", "inputs": {"value": 0}, "_meta": {"title": "NOUS:height"}},
        "5": {"class_type": "INTConstant", "inputs": {"value": -370}, "_meta": {"title": "NOUS:seed"}},
        "6": {"class_type": "LoraLoader", "inputs": {}, "_meta": {"title": "NOUS:lora"}},
        "7": {"class_type": "CheckpointLoaderSimple", "inputs": {}, "_meta": {"title": "NOUS:checkpoint"}},
    }
    out = provider._apply_nous_injections(
        workflow,
        prompt="p1",
        negative_prompt="n1",
        seed=12345,
    )
    assert out["1"]["inputs"]["text"] == "p1"
    assert out["2"]["inputs"]["text"] == "n1"
    assert out["3"]["inputs"]["value"] == 1024  # 既定 width
    assert out["4"]["inputs"]["value"] == 1024  # 既定 height
    assert out["5"]["inputs"]["value"] == 12345  # seed は generate 側で計算された値
    # 廃止タグは無視される（未知タグとして warning ログのみ）
    assert "lora_name" not in out["6"]["inputs"]
    assert "ckpt_name" not in out["7"]["inputs"]


@pytest.mark.asyncio
async def test_workflow_source_comfyui_requires_name():
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    with pytest.raises(ValueError, match="workflow_name"):
        ComfyUIProvider(api_url="http://localhost:8188", workflow_source="comfyui")


@pytest.mark.asyncio
async def test_fetch_userdata_workflow_404():
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(
            api_url="http://localhost:8188", workflow_source="comfyui", workflow_name="missing.json"
        )
        with pytest.raises(FileNotFoundError, match="Workflow not found"):
            await provider._fetch_userdata_workflow()
        # ルートは単一セグメント {file} のためスラッシュを %2F エンコードして叩く
        mock_client.get.assert_awaited_once_with("http://localhost:8188/userdata/workflows%2Fmissing.json")


@pytest.mark.asyncio
async def test_object_info_is_cached():
    """object_info は TTL 内なら再取得しない。"""
    from tests.unit.workflow_fixtures import OBJECT_INFO

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = OBJECT_INFO
        mock_client.get = AsyncMock(return_value=resp)
        mock_client_class.return_value = mock_client

        from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

        provider = ComfyUIProvider(api_url="http://localhost:8188", workflow_source="comfyui", workflow_name="a.json")
        await provider._get_object_info()
        await provider._get_object_info()
        object_info_calls = [c for c in mock_client.get.call_args_list if c.args[0].endswith("/object_info")]
        assert len(object_info_calls) == 1


@pytest.mark.asyncio
async def test_workflow_source_local_rejects_empty_template():
    """従来の local ソースは workflow_template 必須のまま（後方互換）。"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    with pytest.raises(ValueError, match="workflow_template"):
        ComfyUIProvider(api_url="http://localhost:8188", workflow_template="")
