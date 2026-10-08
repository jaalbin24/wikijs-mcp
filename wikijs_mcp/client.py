"""Wiki.js GraphQL API client."""

import json
import logging
import os
import re
import ssl
from typing import Any

import httpx
import truststore

from .config import WikiJSConfig

logger = logging.getLogger(__name__)

# Hard fallback locale used when neither an explicit locale, the
# WIKIJS_DEFAULT_LOCALE environment variable nor the site's primary locale
# can be determined. The upstream code hard-coded "en" here, which broke
# wikis whose primary locale is not English (pages were created in the wrong
# locale and never reached Git storage).
FALLBACK_LOCALE = "de"

# MIME types inferred from the file extension (lowercase, without leading dot).
_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def _mime_for_filename(filename: str) -> str:
    """Derive the MIME type of an asset from its file extension."""
    ext = os.path.splitext(filename.lower())[1]
    return _MIME_TYPES.get(ext, "application/octet-stream")


def _sanitize_filename(name: str) -> str:
    """Best-effort copy of the server-side filename sanitization.

    Wiki.js lowercases filenames and replaces whitespace / `,` `;` `#` with
    underscores (``npm sanitize-filename``). Quotes, angle brackets, pipes and
    path separators are dropped. The server performs the authoritative
    sanitization; this helper only mirrors it so the client can report the
    expected final names.
    """
    name = os.path.basename(name)
    name = name.lower()
    name = re.sub(r"[\s,;#]+", "_", name)
    name = re.sub(r'[\\/*?"<>|]+', "", name)
    return name.strip(" .")


_PAGE_FIELDS_META = """
                    id
                    path
                    title
                    description
                    contentType
                    isPublished
                    isPrivate
                    createdAt
                    updatedAt
                    editor
                    locale
                    authorId
                    authorName
                    authorEmail
                    creatorId
                    creatorName
                    creatorEmail
                    tags {
                        id
                        tag
                        title
                    }"""

_PAGE_FIELDS_FULL = (
    _PAGE_FIELDS_META
    + """
                    content"""
)


class WikiJSClient:
    """Client for interacting with Wiki.js GraphQL API."""

    def __init__(self, config: WikiJSConfig):
        self.config = config
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client = httpx.AsyncClient(timeout=30.0, verify=ctx)
        # Per-instance cache of the resolved default locale.
        self._resolved_locale: str | None = None
        # Cache of asset folder id -> slash-joined lowercase slug path, filled
        # while walking/creating folder hierarchies (see asset_folder_id).
        self._folder_path_cache: dict[int, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _env_locale(self) -> str | None:
        """Return the locale from WIKIJS_DEFAULT_LOCALE, if set."""
        value = (
            self.config.default_locale or os.getenv("WIKIJS_DEFAULT_LOCALE") or ""
        ).strip()
        return value or None

    async def _resolve_locale(self, locale: str | None = None) -> str:
        """Resolve the effective locale for a page operation.

        Resolution order:
        1. Explicit ``locale`` argument (used as-is when provided).
        2. ``WIKIJS_DEFAULT_LOCALE`` environment variable (or
           ``WikiJSConfig.default_locale``).
        3. The wiki's primary locale (``localization.config.locale``), queried
           once per client instance and cached afterwards.
        4. Hard fallback: ``de``.

        Returns:
            The resolved locale code.
        """
        if locale:
            return locale
        if self._resolved_locale is not None:
            return self._resolved_locale

        env_locale = self._env_locale()
        if env_locale:
            self._resolved_locale = env_locale
            return env_locale

        site_locale: str | None = None
        try:
            localization = await self.get_localization_config()
            if isinstance(localization, dict):
                site_locale = localization.get("locale") or None
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Could not query the site's primary locale, falling back to %r: %s",
                FALLBACK_LOCALE,
                exc,
            )

        self._resolved_locale = site_locale or FALLBACK_LOCALE
        return self._resolved_locale

    async def _execute_query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query against the Wiki.js API."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await self.client.post(
                self.config.graphql_url, json=payload, headers=self.config.headers
            )
            response.raise_for_status()
            result = response.json()

            if "errors" in result:
                logger.error(f"GraphQL errors: {result['errors']}")
                raise Exception(f"GraphQL query failed: {result['errors']}")

            return result.get("data", {})

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise Exception(f"API request failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            raise

    async def search_pages(
        self, query: str, limit: int = 10, locale: str | None = None
    ) -> list[dict[str, Any]]:
        """Search for pages by title or content.

        When ``locale`` is omitted the resolved default locale is used (see
        ``_resolve_locale``).
        """
        graphql_query = """
        query SearchPages($query: String!, $path: String, $locale: String) {
            pages {
                search(query: $query, path: $path, locale: $locale) {
                    results {
                        id
                        title
                        description
                        path
                        locale
                    }
                    totalHits
                }
            }
        }
        """

        resolved_locale = await self._resolve_locale(locale)
        variables = {
            "query": query,
            "path": "",
            "locale": resolved_locale,
        }

        result = await self._execute_query(graphql_query, variables)
        results = result.get("pages", {}).get("search", {}).get("results", [])
        return results[:limit]

    async def get_page_by_path(
        self,
        path: str,
        locale: str | None = None,
        metadata_only: bool = False,
        include_render: bool = False,
    ) -> dict[str, Any] | None:
        """Get a page by its path using the singleByPath query.

        When ``locale`` is omitted the resolved default locale is used (see
        ``_resolve_locale``).
        """
        fields = _PAGE_FIELDS_META if metadata_only else _PAGE_FIELDS_FULL
        if include_render:
            fields += "\n                    render"
        graphql_query = f"""
        query GetPageByPath($path: String!, $locale: String!) {{
            pages {{
                singleByPath(path: $path, locale: $locale) {{{fields}
                }}
            }}
        }}
        """

        resolved_locale = await self._resolve_locale(locale)
        result = await self._execute_query(
            graphql_query, {"path": path, "locale": resolved_locale}
        )
        return result.get("pages", {}).get("singleByPath")

    async def get_page_by_id(
        self,
        page_id: int,
        metadata_only: bool = False,
        include_render: bool = False,
    ) -> dict[str, Any] | None:
        """Get a page by its ID using the single query."""
        fields = _PAGE_FIELDS_META if metadata_only else _PAGE_FIELDS_FULL
        if include_render:
            fields += "\n                    render"
        graphql_query = f"""
        query GetPageById($id: Int!) {{
            pages {{
                single(id: $id) {{{fields}
                }}
            }}
        }}
        """

        result = await self._execute_query(graphql_query, {"id": page_id})
        return result.get("pages", {}).get("single")

    async def list_pages(
        self,
        limit: int = 50,
        tags: list[str] | None = None,
        order_by: str = "TITLE",
        order_by_direction: str = "ASC",
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all pages with optional filtering and ordering.

        Unlike reads, no locale filter is applied when ``locale`` is omitted —
        all locales are returned. Pass ``locale`` to restrict the listing to a
        single locale.
        """
        locale_var_clause = ", $locale: String" if locale is not None else ""
        locale_arg_clause = ", locale: $locale" if locale is not None else ""
        graphql_query = f"""
        query ListPages($limit: Int!, $orderBy: PageOrderBy, $orderByDirection: PageOrderByDirection, $tags: [String!]{locale_var_clause}) {{
            pages {{
                list(limit: $limit, orderBy: $orderBy, orderByDirection: $orderByDirection, tags: $tags{locale_arg_clause}) {{
                    id
                    path
                    title
                    description
                    contentType
                    updatedAt
                    createdAt
                    locale
                    tags
                }}
            }}
        }}
        """

        variables: dict[str, Any] = {
            "limit": limit,
            "orderBy": order_by,
            "orderByDirection": order_by_direction,
        }
        if tags is not None:
            variables["tags"] = tags
        if locale is not None:
            variables["locale"] = locale

        result = await self._execute_query(graphql_query, variables)
        return result.get("pages", {}).get("list", [])

    async def get_page_tree(
        self,
        parent_path: str = "",
        mode: str = "ALL",
        locale: str | None = None,
        parent_id: int = None,
    ) -> list[dict[str, Any]]:
        """Get page tree structure using the correct schema.

        When ``locale`` is omitted the resolved default locale is used (see
        ``_resolve_locale``).
        """
        graphql_query = """
        query GetPageTree($path: String, $parent: Int, $mode: PageTreeMode!, $locale: String!, $includeAncestors: Boolean) {
            pages {
                tree(path: $path, parent: $parent, mode: $mode, locale: $locale, includeAncestors: $includeAncestors) {
                    id
                    path
                    depth
                    title
                    isPrivate
                    isFolder
                    privateNS
                    parent
                    pageId
                    locale
                }
            }
        }
        """

        resolved_locale = await self._resolve_locale(locale)
        variables = {
            "path": parent_path if parent_path else None,
            "parent": parent_id,
            "mode": mode,  # ALL, FOLDERS, or PAGES
            "locale": resolved_locale,
            "includeAncestors": False,
        }

        result = await self._execute_query(graphql_query, variables)
        return result.get("pages", {}).get("tree", [])

    async def create_page(
        self,
        path: str,
        title: str,
        content: str,
        description: str = "",
        editor: str = "markdown",
        locale: str | None = None,
        tags: list[str] | None = None,
        is_published: bool = True,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Create a new page using the correct schema.

        When ``locale`` is omitted the resolved default locale is used (see
        ``_resolve_locale``) instead of a hard-coded ``en``.
        """
        graphql_query = """
        mutation CreatePage(
            $content: String!,
            $description: String!,
            $editor: String!,
            $isPublished: Boolean!,
            $isPrivate: Boolean!,
            $locale: String!,
            $path: String!,
            $tags: [String]!,
            $title: String!
        ) {
            pages {
                create(
                    content: $content,
                    description: $description,
                    editor: $editor,
                    isPublished: $isPublished,
                    isPrivate: $isPrivate,
                    locale: $locale,
                    path: $path,
                    tags: $tags,
                    title: $title
                ) {
                    responseResult {
                        succeeded
                        errorCode
                        slug
                        message
                    }
                    page {
                        id
                        path
                        title
                    }
                }
            }
        }
        """

        resolved_locale = await self._resolve_locale(locale)
        variables = {
            "content": content,
            "description": description,
            "editor": editor,
            "isPublished": is_published,
            "isPrivate": is_private,
            "locale": resolved_locale,
            "path": path,
            "tags": tags or [],
            "title": title,
        }

        result = await self._execute_query(graphql_query, variables)
        create_result = result.get("pages", {}).get("create", {})

        response = create_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to create page: {response.get('message', 'Unknown error')}"
            )

        return create_result

    async def update_page(
        self,
        page_id: int,
        content: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        editor: str | None = None,
        is_private: bool | None = None,
        is_published: bool | None = None,
        locale: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing page. Retrieves current page data and merges with updates."""

        # First, get the current page to ensure we have all required fields
        current_page = await self.get_page_by_id(page_id)
        if not current_page:
            raise Exception(f"Page with ID {page_id} not found")

        if locale is not None:
            resolved_locale = await self._resolve_locale(locale)
        else:
            # Preserve the page's current locale on partial updates; only fall
            # back to the resolved default locale when the page has none.
            resolved_locale = current_page.get("locale") or await self._resolve_locale(
                None
            )

        # Merge current values with provided updates
        update_data = {
            "id": page_id,
            "content": (
                content if content is not None else current_page.get("content", "")
            ),
            "title": title if title is not None else current_page.get("title", ""),
            "description": (
                description
                if description is not None
                else current_page.get("description", "")
            ),
            "editor": (
                editor if editor is not None else current_page.get("editor", "markdown")
            ),
            "isPrivate": (
                is_private
                if is_private is not None
                else current_page.get("isPrivate", False)
            ),
            "isPublished": (
                is_published
                if is_published is not None
                else current_page.get("isPublished", True)
            ),
            "locale": resolved_locale,
            "path": path if path is not None else current_page.get("path", ""),
            "tags": tags
            if tags is not None
            else [
                tag.get("tag", tag.get("title", str(tag)))
                for tag in current_page.get("tags", [])
            ],
        }

        graphql_query = """
        mutation UpdatePage(
            $id: Int!,
            $content: String,
            $description: String,
            $editor: String,
            $isPrivate: Boolean,
            $isPublished: Boolean,
            $locale: String,
            $path: String,
            $tags: [String],
            $title: String
        ) {
            pages {
                update(
                    id: $id,
                    content: $content,
                    description: $description,
                    editor: $editor,
                    isPrivate: $isPrivate,
                    isPublished: $isPublished,
                    locale: $locale,
                    path: $path,
                    tags: $tags,
                    title: $title
                ) {
                    responseResult {
                        succeeded
                        errorCode
                        message
                    }
                    page {
                        id
                        path
                        title
                        updatedAt
                    }
                }
            }
        }
        """

        result = await self._execute_query(graphql_query, update_data)
        update_result = result.get("pages", {}).get("update", {})

        response = update_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to update page: {response.get('message', 'Unknown error')}"
            )

        return update_result

    async def delete_page(self, page_id: int) -> dict[str, Any]:
        """Delete a page."""
        graphql_query = """
        mutation DeletePage($id: Int!) {
            pages {
                delete(id: $id) {
                    responseResult {
                        succeeded
                        errorCode
                        message
                    }
                }
            }
        }
        """

        result = await self._execute_query(graphql_query, {"id": page_id})
        delete_result = result.get("pages", {}).get("delete", {})

        response = delete_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to delete page: {response.get('message', 'Unknown error')}"
            )

        return delete_result

    async def move_page(
        self,
        page_id: int,
        destination_path: str,
        destination_locale: str | None = None,
    ) -> dict[str, Any]:
        """Move a page to a new path and/or locale.

        When ``destination_locale`` is omitted the resolved default locale is
        used (see ``_resolve_locale``) instead of a hard-coded ``en``.

        After the move the page is re-read via ``get_page_by_id`` and verified
        to be at the requested path *and* locale. Wiki.js writes the DB first
        and the (Git) storage second; if the storage write fails the page can
        end up in a dirty state (DB moved, storage untouched, later
        move/delete failing with ``ENOENT``). A mismatch is reported loudly.
        """
        resolved_locale = await self._resolve_locale(destination_locale)
        graphql_query = """
        mutation MovePage($id: Int!, $destinationPath: String!, $destinationLocale: String!) {
            pages {
                move(id: $id, destinationPath: $destinationPath, destinationLocale: $destinationLocale) {
                    responseResult {
                        succeeded
                        errorCode
                        message
                    }
                }
            }
        }
        """

        variables = {
            "id": page_id,
            "destinationPath": destination_path,
            "destinationLocale": resolved_locale,
        }

        result = await self._execute_query(graphql_query, variables)
        move_result = result.get("pages", {}).get("move", {})

        response = move_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to move page: {response.get('message', 'Unknown error')}"
            )

        await self._verify_page_move(
            page_id,
            destination_path=destination_path,
            destination_locale=resolved_locale,
        )
        return move_result

    async def _verify_page_move(
        self,
        page_id: int,
        destination_path: str,
        destination_locale: str,
    ) -> None:
        """Verify that a page actually moved to the requested path and locale.

        Raises a descriptive error (with expected vs actual state) when the
        move left the page in a dirty state, e.g. the page was created in the
        wrong locale so the Git storage write never happened.
        """
        moved_page = await self.get_page_by_id(page_id)
        if moved_page is None:
            raise Exception(
                f"Move verification failed for page {page_id}: the page could "
                f"not be found after the move (expected path '{destination_path}' "
                f"and locale '{destination_locale}'). The page may have been "
                f"created with the wrong locale so the storage write never "
                f"happened — DB and storage may be out of sync."
            )

        actual_path = moved_page.get("path")
        actual_locale = moved_page.get("locale")
        if actual_path != destination_path or actual_locale != destination_locale:
            raise Exception(
                f"Move verification failed for page {page_id}: state does not "
                f"match the destination. Expected path '{destination_path}' with "
                f"locale '{destination_locale}', but the page is at path "
                f"'{actual_path}' with locale '{actual_locale}'. "
                f"The page may have been created with a different locale (check "
                f"WIKIJS_DEFAULT_LOCALE / the site's primary locale), or the "
                f"storage write failed — DB and storage may be out of sync."
            )

    # ------------------------------------------------------------------
    # Asset / file manager
    # ------------------------------------------------------------------

    async def asset_folders(self, parent_id: int = 0) -> list[dict[str, Any]]:
        """List asset folders directly below ``parent_id`` (0 = root).

        Requires the ``read:assets`` permission.
        """
        graphql_query = """
        query AssetFolders($parentFolderId: Int!) {
            assets {
                folders(parentFolderId: $parentFolderId) {
                    id
                    slug
                    name
                }
            }
        }
        """

        result = await self._execute_query(
            graphql_query, {"parentFolderId": int(parent_id or 0)}
        )
        return result.get("assets", {}).get("folders", [])

    async def asset_list(
        self, folder_id: int = 0, kind: str = "ALL"
    ) -> list[dict[str, Any]]:
        """List assets in ``folder_id`` (0 = root), filtered by kind.

        ``kind`` is one of ``ALL``, ``IMAGE`` or ``BINARY``. Requires the
        ``read:assets`` permission.
        """
        kind = (kind or "ALL").strip().upper()
        if kind not in ("ALL", "IMAGE", "BINARY"):
            raise ValueError(
                f"Invalid asset kind '{kind}'. Must be one of: ALL, IMAGE, BINARY"
            )
        graphql_query = """
        query AssetList($folderId: Int!, $kind: AssetKind!) {
            assets {
                list(folderId: $folderId, kind: $kind) {
                    id
                    filename
                    ext
                    kind
                    mime
                    fileSize
                    createdAt
                    updatedAt
                    folder {
                        id
                        slug
                        name
                    }
                }
            }
        }
        """

        result = await self._execute_query(
            graphql_query,
            {"folderId": int(folder_id or 0), "kind": kind},
        )
        return result.get("assets", {}).get("list", [])

    async def asset_create_folder(
        self, parent_id: int = 0, slug: str = "", name: str | None = None
    ) -> dict[str, Any]:
        """Create an asset folder below ``parent_id`` (0 = root).

        Note: Wiki.js lowercases the folder slug server-side. Requires the
        ``write:assets`` permission.
        """
        slug = (slug or "").strip().strip("/")
        if not slug:
            raise ValueError("The asset folder slug must not be empty.")
        graphql_query = """
        mutation CreateAssetFolder($parentFolderId: Int!, $slug: String!, $name: String) {
            assets {
                createFolder(parentFolderId: $parentFolderId, slug: $slug, name: $name) {
                    responseResult {
                        succeeded
                        errorCode
                        slug
                        message
                    }
                }
            }
        }
        """

        result = await self._execute_query(
            graphql_query,
            {
                "parentFolderId": int(parent_id or 0),
                "slug": slug,
                "name": name,
            },
        )
        create_result = result.get("assets", {}).get("createFolder", {})
        response = create_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to create asset folder: {response.get('message', 'Unknown error')}"
            )
        return create_result

    async def asset_rename(self, asset_id: int, filename: str) -> dict[str, Any]:
        """Rename an asset. The new filename must keep the asset's extension.

        Requires the ``manage:assets`` permission.
        """
        if not filename or not filename.strip():
            raise ValueError("The new asset filename must not be empty.")
        graphql_query = """
        mutation RenameAsset($id: Int!, $filename: String!) {
            assets {
                renameAsset(id: $id, filename: $filename) {
                    responseResult {
                        succeeded
                        errorCode
                        message
                    }
                }
            }
        }
        """

        result = await self._execute_query(
            graphql_query, {"id": asset_id, "filename": filename}
        )
        rename_result = result.get("assets", {}).get("renameAsset", {})
        response = rename_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to rename asset: {response.get('message', 'Unknown error')}"
            )
        return rename_result

    async def asset_delete(self, asset_id: int) -> dict[str, Any]:
        """Delete an asset. Requires the ``manage:assets`` permission."""
        graphql_query = """
        mutation DeleteAsset($id: Int!) {
            assets {
                deleteAsset(id: $id) {
                    responseResult {
                        succeeded
                        errorCode
                        message
                    }
                }
            }
        }
        """

        result = await self._execute_query(graphql_query, {"id": asset_id})
        delete_result = result.get("assets", {}).get("deleteAsset", {})
        response = delete_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to delete asset: {response.get('message', 'Unknown error')}"
            )
        return delete_result

    async def asset_folder_id(self, folder_path: str | None) -> int:
        """Resolve a slash-separated folder path to its asset folder ID.

        The path is walked from the root; missing folder segments are created
        on the fly via ``assets.createFolder``. Wiki.js lowercases folder
        slugs, so path segments are lowercased here as well — this behavior is
        documented rather than worked around.

        Returns 0 for the root folder (``None`` or empty path). The resolved
        slug paths are cached per client instance so uploaded assets can
        report their full asset path.
        """
        if not folder_path:
            self._folder_path_cache.setdefault(0, "")
            return 0

        segments = [
            seg.strip().lower()
            for seg in folder_path.strip().strip("/").split("/")
            if seg.strip()
        ]
        if not segments:
            self._folder_path_cache.setdefault(0, "")
            return 0

        parent_id = 0
        path_so_far: list[str] = []
        for slug in segments:
            path_so_far.append(slug)
            full_path = "/".join(path_so_far)

            folders = await self.asset_folders(parent_id)
            folder = next((f for f in folders if f.get("slug") == slug), None)
            if folder is None:
                # Folder does not exist yet — create it, then re-list to
                # obtain its id (createFolder does not return the id).
                await self.asset_create_folder(parent_id, slug)
                folders = await self.asset_folders(parent_id)
                folder = next((f for f in folders if f.get("slug") == slug), None)
            if folder is None:
                raise Exception(
                    f"Asset folder segment '{slug}' could neither be found nor "
                    f"created under parent folder {parent_id}. Ensure the API "
                    f"key has the write:assets permission."
                )

            parent_id = int(folder["id"])
            self._folder_path_cache[parent_id] = full_path

        return parent_id

    async def upload_asset(
        self,
        folder_id: int = 0,
        local_path: str | None = None,
        folder_path: str | None = None,
    ) -> dict[str, Any]:
        """Upload a local file as a wiki asset.

        Uses the Wiki.js v2 multipart upload endpoint (``POST /u``) with the
        file field ``mediaUpload`` and the JSON metadata field ``mediaUpload``
        (``{"folderId": N}``). Requires the ``write:assets`` permission.

        ``folder_path`` (slash-separated, missing folders are created) takes
        precedence over ``folder_id`` when both are provided.

        Returns:
            A dict with ``filename`` (sanitized, lowercase + underscores),
            ``mime``, ``folderId``, ``assetPath`` (folder slug path + /
            + filename; just the filename for the root folder), ``url`` and a
            ready-to-paste ``markdownLink``.
        """
        if not local_path:
            raise ValueError("local_path must be provided.")
        local_path = os.path.expanduser(local_path)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")

        if folder_path:
            resolved_id = await self.asset_folder_id(folder_path)
            given_id = int(folder_id or 0)
            if given_id != 0 and given_id != resolved_id:
                raise ValueError(
                    "folder_id and folder_path resolve to different folders "
                    f"({given_id} vs {resolved_id}); use only one of them."
                )
            folder_id = resolved_id
        folder_id = int(folder_id or 0)

        with open(local_path, "rb") as fh:
            file_bytes = fh.read()

        filename = _sanitize_filename(os.path.basename(local_path))
        if not filename:
            raise ValueError(f"Could not derive a usable filename from: {local_path}")
        mime = _mime_for_filename(filename)

        upload_url = f"{self.config.url.rstrip('/')}/u"
        files = {"mediaUpload": (filename, file_bytes, mime)}
        data = {"mediaUpload": json.dumps({"folderId": folder_id})}
        # Multipart requests set their own Content-Type with a boundary, so
        # only the bearer token is forwarded here.
        headers = {"Authorization": self.config.headers["Authorization"]}

        try:
            response = await self.client.post(
                upload_url, files=files, data=data, headers=headers
            )
        except httpx.RequestError as exc:
            raise Exception(f"Upload request to {upload_url} failed: {exc}") from exc

        if response.status_code != 200 or response.text.strip() != "ok":
            hint = (
                "Ensure the API key has the write:assets permission and that "
                "the target folder exists."
            )
            raise Exception(
                f"Upload failed (HTTP {response.status_code}): "
                f"{response.text.strip() or '<empty response>'} [{hint}]"
            )

        folder_slugs = self._folder_path_cache.get(folder_id, "")
        if folder_id == 0:
            folder_slugs = ""
        asset_path = f"{folder_slugs}/{filename}" if folder_slugs else filename

        base_url = self.config.url.rstrip("/")
        url = f"{base_url}/{asset_path}"
        if mime.startswith("image/"):
            markdown_link = f"![{filename}]({url})"
        else:
            markdown_link = f"[{filename}]({url})"

        return {
            "filename": filename,
            "mime": mime,
            "folderId": folder_id,
            "assetPath": asset_path,
            "url": url,
            "markdownLink": markdown_link,
        }

    async def list_tags(self) -> list[dict[str, Any]]:
        """List all tags."""
        graphql_query = """
        query ListTags {
            pages {
                tags {
                    id
                    tag
                    title
                    createdAt
                    updatedAt
                }
            }
        }
        """

        result = await self._execute_query(graphql_query)
        return result.get("pages", {}).get("tags", [])

    async def get_localization_config(self) -> dict[str, Any]:
        """Get the site's localization configuration."""
        graphql_query = """
        query GetLocalizationConfig {
            localization {
                config {
                    locale
                    autoUpdate
                    namespacing
                    namespaces
                }
            }
        }
        """

        result = await self._execute_query(graphql_query)
        return result.get("localization", {}).get("config", {})

    async def get_site_info(self) -> dict[str, Any]:
        """Get site and localization configuration info."""
        graphql_query = """
        query GetSiteConfig {
            site {
                config {
                    title
                    description
                    host
                }
            }
            localization {
                config {
                    locale
                    autoUpdate
                    namespacing
                    namespaces
                }
            }
        }
        """

        result = await self._execute_query(graphql_query)
        site_config = result.get("site", {}).get("config", {})
        localization_config = result.get("localization", {}).get("config", {})

        if localization_config:
            site_config["localization"] = localization_config

        return site_config

    async def get_page_history(
        self,
        page_id: int,
        offset_page: int = 0,
        offset_size: int = 100,
    ) -> dict[str, Any]:
        """Get page edit history."""
        graphql_query = """
        query GetPageHistory($id: Int!, $offsetPage: Int, $offsetSize: Int) {
            pages {
                history(id: $id, offsetPage: $offsetPage, offsetSize: $offsetSize) {
                    trail {
                        versionId
                        versionDate
                        authorId
                        authorName
                        actionType
                        valueBefore
                        valueAfter
                    }
                    total
                }
            }
        }
        """

        variables = {
            "id": page_id,
            "offsetPage": offset_page,
            "offsetSize": offset_size,
        }
        result = await self._execute_query(graphql_query, variables)
        return result.get("pages", {}).get("history", {})

    async def get_page_version(
        self, page_id: int, version_id: int
    ) -> dict[str, Any] | None:
        """Get a specific version of a page."""
        graphql_query = """
        query GetPageVersion($pageId: Int!, $versionId: Int!) {
            pages {
                version(pageId: $pageId, versionId: $versionId) {
                    action
                    authorId
                    authorName
                    content
                    contentType
                    createdAt
                    versionDate
                    description
                    editor
                    isPrivate
                    isPublished
                    locale
                    path
                    tags
                    title
                    versionId
                }
            }
        }
        """

        variables = {"pageId": page_id, "versionId": version_id}
        result = await self._execute_query(graphql_query, variables)
        return result.get("pages", {}).get("version")
