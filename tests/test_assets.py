"""Tests for the asset / file manager fork features.

All HTTP is routed through ``httpx.MockTransport`` — no live wiki access.
"""

import json

import httpx
import pytest

from wikijs_mcp.client import WikiJSClient
from wikijs_mcp.config import WikiJSConfig


def make_client(handler) -> WikiJSClient:
    """Build a WikiJSClient whose HTTP stack is a MockTransport handler."""
    config = WikiJSConfig(
        url="https://test-wiki.example.com",
        api_key="test-api-key-123",
        graphql_endpoint="/graphql",
    )
    client = WikiJSClient(config)
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


class FakeWikiAssets:
    """In-memory stand-in for the Wiki.js v2 asset GraphQL API + /u upload."""

    def __init__(self):
        # folder_id -> {"parent": int|None, "slug": str, "name": str}
        self.folders = {}
        self.next_folder_id = 1
        self.assets = []
        self.created_folders = []  # (parent_id, slug) in creation order
        self.upload_requests = []  # captured httpx.Request objects
        self.upload_status = 200
        self.upload_body = "ok"

    def add_folder(self, parent, slug, name=None):
        folder_id = self.next_folder_id
        self.next_folder_id += 1
        self.folders[folder_id] = {
            "parent": None if parent == 0 or parent is None else parent,
            "slug": slug,
            "name": name or slug,
        }
        return folder_id

    def _children(self, parent_id):
        parent_key = None if parent_id == 0 or parent_id is None else parent_id
        return [
            {"id": fid, "slug": f["slug"], "name": f["name"]}
            for fid, f in sorted(self.folders.items())
            if f["parent"] == parent_key
        ]

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/u":
            self.upload_requests.append(request)
            return httpx.Response(self.upload_status, text=self.upload_body)

        assert request.url.path == "/graphql"
        body = json.loads(request.content)
        query = body["query"]
        variables = body.get("variables", {})

        if "query AssetFolders" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "assets": {
                            "folders": self._children(variables["parentFolderId"])
                        }
                    }
                },
            )

        if "mutation CreateAssetFolder" in query:
            parent = variables["parentFolderId"]
            slug = variables["slug"].lower()  # server lowercases slugs
            self.created_folders.append((parent, slug))
            existing = [f for f in self._children(parent) if f["slug"] == slug]
            if existing:
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "assets": {
                                "createFolder": {
                                    "responseResult": {
                                        "succeeded": False,
                                        "errorCode": 1,
                                        "slug": slug,
                                        "message": "The asset folder already exists.",
                                    }
                                }
                            }
                        }
                    },
                )
            self.add_folder(parent, slug)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "assets": {
                            "createFolder": {
                                "responseResult": {
                                    "succeeded": True,
                                    "errorCode": 0,
                                    "slug": slug,
                                    "message": "Asset Folder has been created successfully.",
                                }
                            }
                        }
                    }
                },
            )

        if "query AssetList" in query:
            folder = variables["folderId"]
            kind = variables["kind"]
            items = [
                a
                for a in self.assets
                if (folder == 0 and a["folder"]["id"] == 0)
                or (a["folder"].get("id") == folder)
            ]
            if kind != "ALL":
                items = [a for a in items if a["kind"] == kind]
            return httpx.Response(200, json={"data": {"assets": {"list": items}}})

        if "mutation RenameAsset" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "assets": {
                            "renameAsset": {
                                "responseResult": {
                                    "succeeded": True,
                                    "errorCode": 0,
                                    "message": "Asset renamed successfully.",
                                }
                            }
                        }
                    }
                },
            )

        if "mutation DeleteAsset" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "assets": {
                            "deleteAsset": {
                                "responseResult": {
                                    "succeeded": True,
                                    "errorCode": 0,
                                    "message": "Asset deleted successfully.",
                                }
                            }
                        }
                    }
                },
            )

        raise AssertionError(f"Unexpected GraphQL operation: {query}")


@pytest.mark.unit
class TestAssetFolderIdWalk:
    """asset_folder_id: resolve existing paths, create missing folders."""

    async def test_existing_path_resolved_without_creating(self):
        wiki = FakeWikiAssets()
        team = wiki.add_folder(0, "team", name="Team")
        wiki.add_folder(team, "manuals", name="Manuals")

        async with make_client(wiki.handle) as client:
            folder_id = await client.asset_folder_id("team/manuals")

        assert folder_id == 2
        assert wiki.created_folders == []
        assert client._folder_path_cache == {
            1: "team",
            2: "team/manuals",
        }

    async def test_partial_path_creates_missing_segments(self):
        wiki = FakeWikiAssets()
        wiki.add_folder(0, "team")

        async with make_client(wiki.handle) as client:
            folder_id = await client.asset_folder_id("team/manuals")

        assert folder_id == 2
        assert wiki.created_folders == [(1, "manuals")]
        assert client._folder_path_cache[2] == "team/manuals"

    async def test_completely_new_path_creates_all_segments(self):
        wiki = FakeWikiAssets()

        async with make_client(wiki.handle) as client:
            folder_id = await client.asset_folder_id("alpha/beta")

        assert folder_id == 2
        assert wiki.created_folders == [(0, "alpha"), (1, "beta")]
        # Wiki.js lowercases slugs — the cache reflects the real slugs.
        assert client._folder_path_cache == {1: "alpha", 2: "alpha/beta"}

    async def test_slug_lowercasing_is_documented_not_worked_around(self):
        wiki = FakeWikiAssets()

        async with make_client(wiki.handle) as client:
            folder_id = await client.asset_folder_id("My Docs/Sub Folder")

        assert folder_id == 2
        assert wiki.created_folders == [(0, "my docs"), (1, "sub folder")]
        assert client._folder_path_cache == {
            1: "my docs",
            2: "my docs/sub folder",
        }

    async def test_root_paths_return_zero(self):
        wiki = FakeWikiAssets()

        async with make_client(wiki.handle) as client:
            assert await client.asset_folder_id(None) == 0
            assert await client.asset_folder_id("") == 0
            assert await client.asset_folder_id("   ") == 0

    async def test_create_folder_reused_on_existing_segment(self):
        wiki = FakeWikiAssets()
        existing_id = wiki.add_folder(0, "docs")
        wiki.add_folder(existing_id, "api")

        async with make_client(wiki.handle) as client:
            folder_id = await client.asset_folder_id("docs/api")

        assert folder_id == existing_id + 1
        assert wiki.created_folders == []


@pytest.mark.unit
class TestUploadAsset:
    """upload_asset: multipart payload shape and result mapping."""

    async def _upload_to_root(self, wiki, tmp_path):
        async with make_client(wiki.handle) as client:
            return await client.upload_asset(0, str(tmp_path / "Report Final.PDF"))

    async def test_upload_multipart_payload_fields(self, tmp_path):
        wiki = FakeWikiAssets()
        (tmp_path / "Report Final.PDF").write_bytes(b"%PDF-1.4 fake pdf payload")

        async with make_client(wiki.handle) as client:
            result = await client.upload_asset(0, str(tmp_path / "Report Final.PDF"))

        assert result["filename"] == "report_final.pdf"
        assert result["mime"] == "application/pdf"
        assert result["assetPath"] == "report_final.pdf"
        assert result["url"] == "https://test-wiki.example.com/report_final.pdf"
        assert result["markdownLink"] == (
            "[report_final.pdf](https://test-wiki.example.com/report_final.pdf)"
        )

        assert len(wiki.upload_requests) == 1
        request = wiki.upload_requests[0]
        assert request.method == "POST"
        assert request.url.path == "/u"
        assert request.headers.get("authorization") == "Bearer test-api-key-123"

        body = request.content.decode("latin-1")
        # File part: field name mediaUpload, with a content-disposition filename.
        assert 'name="mediaUpload"; filename="report_final.pdf"' in body
        assert "Content-Type: application/pdf" in body
        # Metadata part: the other mediaUpload text field carrying folderId JSON.
        assert '"folderId": 0' in body
        # Exactly two parts named mediaUpload (file + JSON metadata).
        assert body.count('name="mediaUpload"') == 2

    async def test_upload_into_nested_folder_returns_asset_path(self, tmp_path):
        wiki = FakeWikiAssets()
        team = wiki.add_folder(0, "team")
        wiki.add_folder(team, "manuals")
        (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 fake")

        async with make_client(wiki.handle) as client:
            result = await client.upload_asset(
                0, str(tmp_path / "report.pdf"), folder_path="team/manuals"
            )

        assert result["folderId"] == 2
        assert result["assetPath"] == "team/manuals/report.pdf"
        assert result["url"] == "https://test-wiki.example.com/team/manuals/report.pdf"
        assert result["markdownLink"] == (
            "[report.pdf](https://test-wiki.example.com/team/manuals/report.pdf)"
        )

    async def test_image_upload_produces_image_markdown(self, tmp_path):
        wiki = FakeWikiAssets()
        (tmp_path / "logo.png").write_bytes(b"\x89PNG fake")

        async with make_client(wiki.handle) as client:
            result = await client.upload_asset(0, str(tmp_path / "logo.png"))

        assert result["mime"] == "image/png"
        assert result["markdownLink"] == (
            "![logo.png](https://test-wiki.example.com/logo.png)"
        )

    async def test_upload_missing_local_file(self, tmp_path):
        wiki = FakeWikiAssets()

        with pytest.raises(FileNotFoundError):
            async with make_client(wiki.handle) as client:
                await client.upload_asset(0, str(tmp_path / "nope.pdf"))

    async def test_upload_permission_error_is_surfaced(self, tmp_path):
        wiki = FakeWikiAssets()
        wiki.upload_status = 403
        wiki.upload_body = json.dumps(
            {"succeeded": False, "message": "You are not authorized to upload files."}
        )
        (tmp_path / "a.pdf").write_bytes(b"fake")

        with pytest.raises(Exception, match="write:assets"):
            async with make_client(wiki.handle) as client:
                await client.upload_asset(0, str(tmp_path / "a.pdf"))

    async def test_upload_non_ok_body_is_surfaced(self, tmp_path):
        wiki = FakeWikiAssets()
        wiki.upload_body = "<html>500 Internal Server Error</html>"
        (tmp_path / "a.pdf").write_bytes(b"fake")

        with pytest.raises(Exception, match="Upload failed"):
            async with make_client(wiki.handle) as client:
                await client.upload_asset(0, str(tmp_path / "a.pdf"))

    async def test_upload_folder_path_conflict_raises(self, tmp_path):
        wiki = FakeWikiAssets()
        wiki.add_folder(0, "team")
        (tmp_path / "a.pdf").write_bytes(b"fake")

        with pytest.raises(ValueError, match="different folders"):
            async with make_client(wiki.handle) as client:
                await client.upload_asset(
                    3, str(tmp_path / "a.pdf"), folder_path="team"
                )


@pytest.mark.unit
class TestAssetCrud:
    """asset_folders / asset_list / asset_create_folder / rename / delete."""

    async def test_asset_folders_lists_children(self):
        wiki = FakeWikiAssets()
        team = wiki.add_folder(0, "team")
        wiki.add_folder(team, "manuals")

        async with make_client(wiki.handle) as client:
            children = await client.asset_folders(0)

        assert [c["slug"] for c in children] == ["team"]
        assert children[0]["id"] == team
        assert children[0]["name"] == "team"

    async def test_asset_create_folder_success(self):
        wiki = FakeWikiAssets()

        async with make_client(wiki.handle) as client:
            result = await client.asset_create_folder(0, "TeamDocs")

        response = result["responseResult"]
        assert response["succeeded"] is True
        assert "created successfully" in response["message"].lower()
        # The slug handed to the server is lowercased.
        assert wiki.created_folders == [(0, "teamdocs")]

    async def test_asset_create_folder_failure_raises(self):
        wiki = FakeWikiAssets()
        wiki.add_folder(0, "docs")

        with pytest.raises(Exception, match="already exists"):
            async with make_client(wiki.handle) as client:
                await client.asset_create_folder(0, "docs")

    async def test_asset_list_filters_by_kind(self):
        wiki = FakeWikiAssets()
        folder = wiki.add_folder(0, "files")
        wiki.assets = [
            {"id": 1, "filename": "a.png", "kind": "IMAGE", "folder": {"id": folder}},
            {"id": 2, "filename": "b.png", "kind": "IMAGE", "folder": {"id": folder}},
            {"id": 3, "filename": "c.pdf", "kind": "BINARY", "folder": {"id": folder}},
        ]

        async with make_client(wiki.handle) as client:
            images = await client.asset_list(folder, kind="IMAGE")

        assert [a["filename"] for a in images] == ["a.png", "b.png"]

    async def test_asset_rename_and_delete_success(self):
        wiki = FakeWikiAssets()

        async with make_client(wiki.handle) as client:
            rename_result = await client.asset_rename(7, "new_name.pdf")
            delete_result = await client.asset_delete(7)

        assert rename_result["responseResult"]["succeeded"] is True
        assert delete_result["responseResult"]["succeeded"] is True
