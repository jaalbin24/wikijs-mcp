"""Wiki.js GraphQL API client."""

import logging
import ssl
from typing import Any

import httpx
import truststore

from .config import WikiJSConfig

logger = logging.getLogger(__name__)


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

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

    async def search_pages(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for pages by title or content."""
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

        variables = {
            "query": query,
            "path": "",
            "locale": "en",
        }

        result = await self._execute_query(graphql_query, variables)
        results = result.get("pages", {}).get("search", {}).get("results", [])
        return results[:limit]

    async def get_page_by_path(
        self,
        path: str,
        locale: str = "en",
        metadata_only: bool = False,
        include_render: bool = False,
    ) -> dict[str, Any] | None:
        """Get a page by its path using the singleByPath query."""
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

        result = await self._execute_query(
            graphql_query, {"path": path, "locale": locale}
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
    ) -> list[dict[str, Any]]:
        """List all pages with optional filtering and ordering."""
        graphql_query = """
        query ListPages($limit: Int!, $orderBy: PageOrderBy, $orderByDirection: PageOrderByDirection, $tags: [String!]) {
            pages {
                list(limit: $limit, orderBy: $orderBy, orderByDirection: $orderByDirection, tags: $tags) {
                    id
                    path
                    title
                    description
                    contentType
                    updatedAt
                    createdAt
                    locale
                    tags
                }
            }
        }
        """

        variables: dict[str, Any] = {
            "limit": limit,
            "orderBy": order_by,
            "orderByDirection": order_by_direction,
        }
        if tags is not None:
            variables["tags"] = tags

        result = await self._execute_query(graphql_query, variables)
        return result.get("pages", {}).get("list", [])

    async def get_page_tree(
        self,
        parent_path: str = "",
        mode: str = "ALL",
        locale: str = "en",
        parent_id: int = None,
    ) -> list[dict[str, Any]]:
        """Get page tree structure using the correct schema."""
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

        variables = {
            "path": parent_path if parent_path else None,
            "parent": parent_id,
            "mode": mode,  # ALL, FOLDERS, or PAGES
            "locale": locale,
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
        locale: str = "en",
        tags: list[str] | None = None,
        is_published: bool = True,
        is_private: bool = False,
    ) -> dict[str, Any]:
        """Create a new page using the correct schema."""
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

        variables = {
            "content": content,
            "description": description,
            "editor": editor,
            "isPublished": is_published,
            "isPrivate": is_private,
            "locale": locale,
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
            "locale": (
                locale if locale is not None else current_page.get("locale", "en")
            ),
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
        self, page_id: int, destination_path: str, destination_locale: str = "en"
    ) -> dict[str, Any]:
        """Move a page to a new path and/or locale."""
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
            "destinationLocale": destination_locale,
        }

        result = await self._execute_query(graphql_query, variables)
        move_result = result.get("pages", {}).get("move", {})

        response = move_result.get("responseResult", {})
        if not response.get("succeeded"):
            raise Exception(
                f"Failed to move page: {response.get('message', 'Unknown error')}"
            )

        return move_result

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

    async def get_site_info(self) -> dict[str, Any]:
        """Get site configuration info."""
        graphql_query = """
        query GetSiteConfig {
            site {
                config {
                    title
                    description
                    host
                }
            }
        }
        """

        result = await self._execute_query(graphql_query)
        return result.get("site", {}).get("config", {})

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
