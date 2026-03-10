from pathlib import Path

from raganything.parser import MineruAPIParser


def test_mineru_api_markdown_to_content_list_multimodal(tmp_path: Path):
    parser = MineruAPIParser()

    image_file = tmp_path / "fig1.png"
    image_file.write_bytes(b"fake-image")

    markdown = """
# Page 2

Some intro text.

![chart](images/fig1.png)

| name | value |
|------|-------|
| foo  |  1    |

$$
E = mc^2
$$
"""

    content_list = parser._markdown_to_content_list(
        markdown=markdown,
        image_map={"images/fig1.png": str(image_file.resolve())},
        output_dir=tmp_path,
    )

    types = [item.get("type") for item in content_list]
    assert "text" in types
    assert "image" in types
    assert "table" in types
    assert "equation" in types

    image_item = next(item for item in content_list if item.get("type") == "image")
    assert image_item["img_path"] == str(image_file.resolve())
    assert image_item["image_caption"] == ["chart"]
    assert image_item["page_idx"] == 1

    table_item = next(item for item in content_list if item.get("type") == "table")
    assert "| name | value |" in table_item["table_body"]
    assert table_item["page_idx"] == 1

    equation_item = next(item for item in content_list if item.get("type") == "equation")
    assert "E = mc^2" in equation_item["latex"]
    assert equation_item["page_idx"] == 1

