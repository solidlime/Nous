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


# ============================================================
# NOUS tag injection tests (template mode)
# ============================================================


def test_nous_injects_simple_keys():
    """NOUS:タグが対応するinputsフィールドに設定値を注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(
        workflow_template="dummy.json",
        checkpoint="ck.safetensors",
        width=768,
        height=512,
        steps=10,
        cfg=3.0,
        sampler="euler",
        scheduler="sgm_uniform",
        seed=123,
        denoise=0.5,
    )
    workflow = {
        "1": {"class_type": "KSampler", "inputs": {"seed": 0}, "_meta": {"title": "NOUS:seed"}},
        "2": {"class_type": "EmptyLatentImage", "inputs": {}, "_meta": {"title": "NOUS:width"}},
        "3": {"class_type": "EmptyLatentImage", "inputs": {}, "_meta": {"title": "NOUS:height"}},
        "4": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": "NOUS:steps"}},
        "5": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": "NOUS:cfg"}},
        "6": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": "NOUS:sampler"}},
        "7": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": "NOUS:scheduler"}},
        "8": {"class_type": "KSampler", "inputs": {}, "_meta": {"title": "NOUS:denoise"}},
        "9": {"class_type": "CheckpointLoaderSimple", "inputs": {}, "_meta": {"title": "NOUS:checkpoint"}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {}, "_meta": {"title": "NOUS:prompt"}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {}, "_meta": {"title": "NOUS:negative_prompt"}},
    }
    provider._apply_nous_injections(
        workflow,
        prompt="a cat",
        negative_prompt="bad anatomy",
        image_filename=None,
        seed=123,
    )
    assert workflow["1"]["inputs"]["seed"] == 123
    assert workflow["1"]["inputs"]["noise_seed"] == 123
    assert workflow["2"]["inputs"]["width"] == 768
    assert workflow["3"]["inputs"]["height"] == 512
    assert workflow["4"]["inputs"]["steps"] == 10
    assert workflow["5"]["inputs"]["cfg"] == 3.0
    assert workflow["6"]["inputs"]["sampler_name"] == "euler"
    assert workflow["7"]["inputs"]["scheduler"] == "sgm_uniform"
    assert workflow["8"]["inputs"]["denoise"] == 0.5
    assert workflow["9"]["inputs"]["ckpt_name"] == "ck.safetensors"
    assert workflow["10"]["inputs"]["text"] == "a cat"
    assert workflow["11"]["inputs"]["text"] == "bad anatomy"


def test_nous_negative_prompt_empty_passthrough():
    """NOUS:negative_prompt は空なら空のまま（デフォルト値は使わない）"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {}, "_meta": {"title": "NOUS:negative_prompt"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    assert workflow["1"]["inputs"]["text"] == ""


def test_nous_reference_image_injects_filename():
    """NOUS:reference_image はアップロード済みファイル名を注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {"1": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": "NOUS:reference_image"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename="ref.png", seed=1)
    assert workflow["1"]["inputs"]["image"] == "ref.png"


def test_nous_reference_image_raises_without_image():
    """NOUS:reference_image タグがあるのに参照画像が無ければ ValueError"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {"1": {"class_type": "LoadImage", "inputs": {}, "_meta": {"title": "NOUS:reference_image"}}}
    with pytest.raises(ValueError, match="参照画像がありません"):
        provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)


def test_nous_lora_single_uses_tagged_node():
    """LoRAが1件ならタグ付きノード自身に注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[{"path": "char", "weight": 0.8}])
    workflow = {
        "4": {
            "class_type": "LoraLoader",
            "inputs": {"model": ["3", 0], "clip": ["3", 1]},
            "_meta": {"title": "NOUS:lora"},
        }
    }
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    inputs = workflow["4"]["inputs"]
    assert inputs["lora_name"] == "char.safetensors"
    assert inputs["strength_model"] == 0.8
    assert inputs["strength_clip"] == 0.8
    assert inputs["model"] == ["3", 0]
    assert inputs["clip"] == ["3", 1]


def test_nous_lora_chain_creates_nodes_and_remaps():
    """LoRAが複数ならチェーンを構築し、参照を最終ノードへ張り替える"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[{"path": "a.safetensors", "weight": 1.0}, {"path": "b.safetensors", "weight": 0.5}])
    workflow = {
        "4": {
            "class_type": "LoraLoader",
            "inputs": {"model": ["3", 0], "clip": ["3", 1]},
            "_meta": {"title": "NOUS:lora"},
        },
        "5": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["6", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1]}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0]}},
    }
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)

    # タグ付きノードはチェーン先頭（1つ目のLoRA）
    assert workflow["4"]["inputs"]["lora_name"] == "a.safetensors"
    assert workflow["4"]["inputs"]["strength_model"] == 1.0

    # 新規ノード: max_id=7 なので "8"
    new_id = "8"
    assert new_id in workflow
    assert workflow[new_id]["class_type"] == "LoraLoader"
    assert workflow[new_id]["inputs"]["lora_name"] == "b.safetensors"
    assert workflow[new_id]["inputs"]["strength_model"] == 0.5
    assert workflow[new_id]["inputs"]["model"] == ["4", 0]
    assert workflow[new_id]["inputs"]["clip"] == ["4", 1]

    # タグ付きノード(4)の MODEL(0)/CLIP(1) 参照 → 最終ノード(8)
    assert workflow["5"]["inputs"]["model"] == [new_id, 0]
    assert workflow["6"]["inputs"]["clip"] == [new_id, 1]
    # 無関係な参照は変わらない
    assert workflow["7"]["inputs"]["samples"] == ["5", 0]


def test_nous_lora_empty_config_leaves_node_untouched():
    """LoRA設定が空ならタグ付きノードに手を加えない"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[])
    workflow = {
        "4": {
            "class_type": "LoraLoader",
            "inputs": {"model": ["3", 0], "clip": ["3", 1]},
            "_meta": {"title": "NOUS:lora"},
        }
    }
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    assert workflow["4"]["inputs"] == {"model": ["3", 0], "clip": ["3", 1]}
    assert len(workflow) == 1


def test_nous_int_constant_injects_value_field():
    """INTConstant ノードは数値系タグを inputs["value"]（int）に注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", width=768, height=512, steps=10)
    workflow = {
        "1": {"class_type": "INTConstant", "inputs": {}, "_meta": {"title": "NOUS:seed"}},
        "2": {"class_type": "INTConstant", "inputs": {}, "_meta": {"title": "NOUS:width"}},
        "3": {"class_type": "INTConstant", "inputs": {}, "_meta": {"title": "NOUS:height"}},
        "4": {"class_type": "INTConstant", "inputs": {}, "_meta": {"title": "NOUS:steps"}},
    }
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=42)
    assert workflow["1"]["inputs"] == {"value": 42}
    assert workflow["2"]["inputs"] == {"value": 768}
    assert workflow["3"]["inputs"] == {"value": 512}
    assert workflow["4"]["inputs"] == {"value": 10}


def test_nous_float_constant_injects_value_field():
    """FloatConstant ノードは cfg/denoise を inputs["value"]（float）に注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", cfg=3.0, denoise=0.5)
    workflow = {
        "1": {"class_type": "FloatConstant", "inputs": {}, "_meta": {"title": "NOUS:cfg"}},
        "2": {"class_type": "FloatConstant", "inputs": {}, "_meta": {"title": "NOUS:denoise"}},
    }
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    assert workflow["1"]["inputs"] == {"value": 3.0}
    assert workflow["2"]["inputs"] == {"value": 0.5}


def test_nous_constant_branch_keeps_non_constant_behavior():
    """非定数ノードは従来どおりセマンティックフィールドへ注入される（定数分岐の影響なし）"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", checkpoint="ck.safetensors")
    workflow = {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {}, "_meta": {"title": "NOUS:checkpoint"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    assert workflow["1"]["inputs"] == {"ckpt_name": "ck.safetensors"}


def test_nous_lora_power_loader_slots():
    """Power Lora Loader は lora_1..lora_5 スロットにオブジェクト形式で注入する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[{"path": "a", "weight": 1.0}, {"path": "b.safetensors", "weight": 0.3}])
    workflow = {"9": {"class_type": "Power Lora Loader", "inputs": {}, "_meta": {"title": "NOUS:lora"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    inputs = workflow["9"]["inputs"]
    assert inputs["lora_1"] == {"on": True, "lora": "a.safetensors", "strength": 1.0}
    assert inputs["lora_2"] == {"on": True, "lora": "b.safetensors", "strength": 0.3}
    assert inputs["lora_3"] == ""
    assert inputs["lora_4"] == ""
    assert inputs["lora_5"] == ""


def test_nous_lora_power_loader_empty_config_disables_all_slots():
    """Power Lora Loader は LoRA 設定が空なら全スロットを無効化する"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[])
    workflow = {"9": {"class_type": "Power Lora Loader", "inputs": {}, "_meta": {"title": "NOUS:lora"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    inputs = workflow["9"]["inputs"]
    assert all(inputs[f"lora_{i}"] == "" for i in range(1, 6))


def test_nous_lora_unsupported_class_type_skipped():
    """対応外の class_type の NOUS:lora タグはスキップされる"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json", loras=[{"path": "a.safetensors", "weight": 1.0}])
    workflow = {"1": {"class_type": "SomeOtherLoader", "inputs": {}, "_meta": {"title": "NOUS:lora"}}}
    provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
    assert workflow["1"]["inputs"] == {}


def test_nous_no_tags_leaves_workflow_unchanged():
    """NOUS:タグが無ければワークフローは変更されない"""
    from nous.infrastructure.image_gen.comfyui import ComfyUIProvider

    provider = ComfyUIProvider(workflow_template="dummy.json")
    workflow = {
        "1": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 512}},
    }
    result = provider._apply_nous_injections(workflow, prompt="x", negative_prompt="", image_filename=None, seed=1)
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
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["5", 0],
                    },
                    "_meta": {"title": "NOUS:seed"},
                },
                "4": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "old.safetensors"},
                    "_meta": {"title": "NOUS:checkpoint"},
                },
                "5": {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": 512, "height": 512, "batch_size": 1},
                    "_meta": {"title": "NOUS:width"},
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "x", "clip": ["4", 1]},
                    "_meta": {"title": "NOUS:prompt"},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": "x", "clip": ["4", 1]},
                    "_meta": {"title": "NOUS:negative_prompt"},
                },
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
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
            checkpoint="new.safetensors",
            width=1024,
            height=2048,
            seed=123,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            images = await provider.generate(prompt="a cat", n=1)

        sent = mock_client.post.call_args[1]["json"]["prompt"]
        assert sent["3"]["inputs"]["seed"] == 123
        assert sent["3"]["inputs"]["noise_seed"] == 123
        assert sent["4"]["inputs"]["ckpt_name"] == "new.safetensors"
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
            seed=42,
            width=768,
            height=640,
        )
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            await provider.generate(prompt="hello", n=1)

        sent = mock_client.post.call_args[1]["json"]["prompt"]
        assert sent["3"]["inputs"]["seed"] == "42"
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

    images = await provider._poll_result(
        "pid", prompt="cat", size="512x512", n=1, node_titles={"10": "upscale"}
    )
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
    config.image_gen_comfyui_loras = ""
    config.image_gen_comfyui_url = "http://localhost:8188"

    settings = MagicMock()
    settings.data_root = str(tmp_path)
    monkeypatch.setattr("nous.config.settings.get_settings", lambda: settings)

    # i2i（固定）: 参照画像 reference.png が必須
    ref_dir = tmp_path / "persona" / "test_persona" / "images"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "reference.png").write_bytes(b"fake_ref_png")

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
    saved = sorted(
        p
        for p in (tmp_path / "persona" / "test_persona" / "images").glob("*.png")
        if p.name != "reference.png"
    )
    assert len(saved) == 2
    assert saved[0].name.endswith("_00.png")
    assert saved[1].name.endswith("_01.png")
