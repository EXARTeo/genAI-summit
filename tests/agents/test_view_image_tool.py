"""The ``view_image`` tool: putting a picture in front of the model.

The load-bearing detail is the return type: a ``ToolMessage`` carrying an image
**content block**. A JSON string of base64 would reach the model as text and be
worth nothing, so these tests assert on the block, not on a string.

Zooming is the second half: a region is in pixels of the full image, so every
result states the dimensions the model needs to aim one. A tight crop is scaled
up, an overshooting one is clamped rather than refused, and one that misses
entirely is an error.

Everything else is about not failing the user's run: a missing file, an
unsupported type, an oversized file and a path outside the two folders all come
back as readable error results. The images are real rows of the in-memory
conversation store, uploads included.
"""

from __future__ import annotations

import base64
import io

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID
from PIL import Image

from core.settings import settings
from harness.conversation_files.inputs import UPLOAD_WRITER
from harness.tools import registry
from harness.tools.builtins import BUILTIN_BY_NAME
from harness.tools.view_image import tool as view_image

# A 1x1 PNG: small, real, and decodable.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def make_png(width: int, height: int) -> bytes:
    """A real image of known size, so crops can be asserted on."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def image_block(message):
    blocks = message.content if isinstance(message.content, list) else []
    return next(b for b in blocks if b.get("type") == "image")


def text_note(message):
    blocks = message.content if isinstance(message.content, list) else []
    return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def decoded_size(message):
    raw = base64.b64decode(image_block(message)["base64"])
    with Image.open(io.BytesIO(raw)) as img:
        return img.size


@pytest.fixture
def put(memory_file_store):
    """Store a file in the conversation, as an upload (input/) or an output."""

    async def _put(path: str, data: bytes) -> None:
        slug = UPLOAD_WRITER if path.startswith("/conversation/input/") else "assistant"
        await memory_file_store.replace(CLIENT_ID, CONVERSATION_ID, path, data, agent_slug=slug)

    return _put


@pytest.fixture
def tool(conversation_files):
    return view_image.build_view_image_tool(files=conversation_files)


async def _run(tool, args, call_id="call-1"):
    """Drive the tool the way LangChain does, so the id injection is exercised."""
    return await tool.ainvoke(
        {"name": "view_image", "args": args, "id": call_id, "type": "tool_call"}
    )


async def _invoke(tool, path, call_id="call-1"):
    return await _run(tool, {"path": path}, call_id)


async def _invoke_region(tool, path, x, y, width, height):
    return await _run(
        tool, {"path": path, "region": {"x": x, "y": y, "width": width, "height": height}}
    )


# ---------------------------------------------------------------------------
# The image reaches the model
# ---------------------------------------------------------------------------
async def test_it_returns_the_image_as_a_content_block(tool, put):
    await put("/conversation/input/shot.png", PNG_BYTES)

    message = await _invoke(tool, "/conversation/input/shot.png")

    assert message.status == "success"
    block = image_block(message)
    assert block["mime_type"] == "image/png"
    # The model's copy is the whole file, not a thumbnail: shrinking happens
    # later and only on the stream.
    assert base64.b64decode(block["base64"]) == PNG_BYTES


async def test_the_tool_call_id_is_injected_not_asked_of_the_model(tool, put):
    # The model must never be prompted for tool_call_id; LangChain supplies it.
    assert "tool_call_id" not in tool.tool_call_schema.model_fields
    assert "path" in tool.tool_call_schema.model_fields

    await put("/conversation/input/shot.png", PNG_BYTES)
    message = await _invoke(tool, "/conversation/input/shot.png", call_id="abc-123")
    assert message.tool_call_id == "abc-123"


async def test_it_reads_from_the_output_folder_too(tool, put):
    await put("/conversation/output/chart.png", PNG_BYTES)
    message = await _invoke(tool, "/conversation/output/chart.png")
    assert message.status == "success"


async def test_a_path_is_normalised_before_it_is_read(tool, put):
    await put("/conversation/input/shot.png", PNG_BYTES)
    message = await _invoke(tool, "  /conversation//input/shot.png")
    assert message.status == "success"


# ---------------------------------------------------------------------------
# Failures are results, never exceptions
# ---------------------------------------------------------------------------
async def test_a_missing_file_says_it_does_not_exist(tool):
    message = await _invoke(tool, "/conversation/input/nope.png")

    assert message.status == "error"
    assert "does not exist in this filesystem" in message.content


@pytest.mark.parametrize(
    "path", ["/reference/secret.png", "/conversation/notes.png", "/large_tool_results/x.png"]
)
async def test_a_path_outside_input_and_output_is_refused(tool, path):
    message = await _invoke(tool, path)

    assert message.status == "error"
    assert "must be under /conversation/input/" in message.content


async def test_a_traversal_is_refused(tool):
    message = await _invoke(tool, "/conversation/input/../../etc/x.png")
    assert message.status == "error"
    assert "Could not view the image" in message.content


async def test_a_non_image_is_refused_before_it_is_read(tool, put):
    await put("/conversation/input/notes.txt", b"hello")

    message = await _invoke(tool, "/conversation/input/notes.txt")

    assert message.status == "error"
    assert "not a viewable image" in message.content


async def test_an_oversized_image_is_refused(tool, put, monkeypatch):
    await put("/conversation/input/big.png", PNG_BYTES)
    monkeypatch.setattr(settings.filesystem, "view_image_max_bytes", 1)

    message = await _invoke(tool, "/conversation/input/big.png")

    assert message.status == "error"
    assert "too large to view" in message.content


async def test_an_undecodable_image_cannot_be_zoomed(tool, put):
    await put("/conversation/input/broken.png", b"not a png at all")

    whole = await _invoke(tool, "/conversation/input/broken.png")
    zoomed = await _invoke_region(tool, "/conversation/input/broken.png", 0, 0, 10, 10)

    # The whole file is still handed over (the model may make sense of it);
    # a crop needs pixels and says so.
    assert whole.status == "success"
    assert zoomed.status == "error"
    assert "could not be decoded" in zoomed.content


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg", ".gif", ".webp", ".PNG"])
async def test_the_supported_formats_are_accepted(tool, put, suffix):
    await put(f"/conversation/input/pic{suffix}", PNG_BYTES)

    message = await _invoke(tool, f"/conversation/input/pic{suffix}")
    assert message.status == "success"


# ---------------------------------------------------------------------------
# How it is offered
# ---------------------------------------------------------------------------
def test_it_is_an_ungated_builtin_that_needs_conversation_files():
    assert "view_image" in registry.NATIVE_TOOLS
    entry = BUILTIN_BY_NAME["view_image"]
    # Reading a picture changes nothing: no approval by default.
    assert entry.hitl_default is False
    assert entry.locked is False

    ctx = registry.NativeToolContext(agent_slug="assistant", conversation_id="")
    assert registry.NATIVE_TOOLS["view_image"].builder(ctx) is None


def test_with_conversation_files_it_is_built(conversation_files):
    ctx = registry.NativeToolContext(
        agent_slug="assistant", conversation_id=CONVERSATION_ID, files=conversation_files
    )
    assert registry.NATIVE_TOOLS["view_image"].builder(ctx).name == "view_image"


# ---------------------------------------------------------------------------
# Zooming
# ---------------------------------------------------------------------------
async def test_a_full_view_reports_the_dimensions_a_zoom_needs(tool, put):
    # Without this the model has no coordinate space to aim a region at.
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke(tool, "/conversation/input/big.png")

    assert "1600x900" in text_note(message)


async def test_a_region_crops_to_that_rectangle(tool, put):
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke_region(tool, "/conversation/input/big.png", 100, 50, 800, 400)

    assert message.status == "success"
    note = text_note(message)
    assert "x=100" in note
    assert "y=50" in note
    assert "w=800" in note
    assert "h=400" in note
    # 800x400 already clears the detail floor, so it is not rescaled.
    assert decoded_size(message) == (800, 400)


async def test_a_tight_crop_is_enlarged_so_the_detail_is_legible(tool, put):
    # The point of zooming is to read small things; handing back the native
    # 80x40 slice would waste the round trip.
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke_region(tool, "/conversation/input/big.png", 10, 10, 80, 40)

    width, height = decoded_size(message)
    assert width > 80
    assert height > 40
    # Scaled towards the detail floor, but never past the upscale cap: an 80px
    # crop lands on the cap (480px), not on the 768px floor.
    assert max(width, height) == min(view_image.MIN_DETAIL_EDGE, round(80 * view_image.MAX_UPSCALE))
    assert width / height == pytest.approx(2.0, rel=0.02)  # aspect preserved
    assert "shown at" in text_note(message)


async def test_a_mid_sized_crop_reaches_the_detail_floor_exactly(tool, put):
    # 200px is within 6x of the floor, so this one is not cap-limited.
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke_region(tool, "/conversation/input/big.png", 0, 0, 200, 100)

    assert max(decoded_size(message)) == view_image.MIN_DETAIL_EDGE


async def test_an_enormous_region_is_capped_rather_than_sent_whole(tool, put):
    await put("/conversation/input/huge.png", make_png(4000, 3000))

    message = await _invoke_region(tool, "/conversation/input/huge.png", 0, 0, 4000, 3000)

    assert max(decoded_size(message)) == view_image.MAX_DETAIL_EDGE


async def test_a_region_overshooting_an_edge_is_clamped_not_refused(tool, put):
    # A model estimating coordinates off a previous look routinely overshoots;
    # failing that costs a round trip to learn nothing.
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke_region(tool, "/conversation/input/big.png", 1500, 800, 500, 500)

    assert message.status == "success"
    note = text_note(message)
    assert "clamped" in note
    assert "w=100" in note
    assert "h=100" in note


async def test_a_region_entirely_off_the_image_is_an_error(tool, put):
    await put("/conversation/input/big.png", make_png(1600, 900))

    message = await _invoke_region(tool, "/conversation/input/big.png", 5000, 5000, 100, 100)

    assert message.status == "error"
    assert "outside the image" in message.content
    assert "1600x900" in message.content


async def test_a_transparent_crop_stays_png(tool, put):
    buffer = io.BytesIO()
    Image.new("RGBA", (600, 600), (10, 120, 200, 128)).save(buffer, format="PNG")
    await put("/conversation/input/alpha.png", buffer.getvalue())

    message = await _invoke_region(tool, "/conversation/input/alpha.png", 0, 0, 300, 300)

    assert image_block(message)["mime_type"] == "image/png"


async def test_an_opaque_crop_is_sent_as_jpeg(tool, put):
    await put("/conversation/input/big.png", make_png(1600, 900))
    message = await _invoke_region(tool, "/conversation/input/big.png", 0, 0, 800, 400)
    assert image_block(message)["mime_type"] == "image/jpeg"


def test_the_region_is_optional_in_the_model_facing_schema(tool):
    schema = tool.tool_call_schema.model_json_schema()
    assert "path" in schema["required"]
    assert "region" not in schema.get("required", [])


class TestClampRegion:
    """The clamp rule on its own, away from file IO."""

    def test_a_contained_region_is_untouched(self):
        region = view_image._Region(x=10, y=20, width=30, height=40)
        assert view_image.clamp_region(region, 100, 100) == (10, 20, 40, 60)

    def test_it_trims_to_the_edges(self):
        region = view_image._Region(x=90, y=90, width=50, height=50)
        assert view_image.clamp_region(region, 100, 100) == (90, 90, 100, 100)

    def test_a_region_starting_past_the_edge_misses(self):
        region = view_image._Region(x=100, y=0, width=10, height=10)
        assert view_image.clamp_region(region, 100, 100) is None


async def test_a_path_with_trailing_whitespace_is_viewed(tool, put):
    # The suffix is read from the normalised path, so stray whitespace the
    # model adds around a path never turns a PNG into "not an image".
    await put("/conversation/input/shot.png", PNG_BYTES)

    message = await _invoke(tool, "/conversation/input/shot.png  ")

    assert message.status == "success"
