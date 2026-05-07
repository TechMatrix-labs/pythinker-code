import mcp.types

import pythinker_core.message


def convert_mcp_content(part: mcp.types.ContentBlock) -> pythinker_core.message.ContentPart:
    """Convert MCP content block to Pythinker Core message content part.

    Raises:
        ValueError: If the content type or mime type is not supported.
    """
    match part:
        case mcp.types.TextContent(text=text):
            return pythinker_core.message.TextPart(text=text)
        case mcp.types.ImageContent(data=data, mimeType=mimeType):
            return pythinker_core.message.ImageURLPart(
                image_url=pythinker_core.message.ImageURLPart.ImageURL(
                    url=f"data:{mimeType};base64,{data}"
                )
            )

        case mcp.types.AudioContent(data=data, mimeType=mimeType):
            return pythinker_core.message.AudioURLPart(
                audio_url=pythinker_core.message.AudioURLPart.AudioURL(
                    url=f"data:{mimeType};base64,{data}"
                )
            )
        case mcp.types.EmbeddedResource(
            resource=mcp.types.BlobResourceContents(uri=_uri, mimeType=mimeType, blob=blob)
        ):
            mimeType = mimeType or "application/octet-stream"
            if mimeType.startswith("image/"):
                return pythinker_core.message.ImageURLPart(
                    type="image_url",
                    image_url=pythinker_core.message.ImageURLPart.ImageURL(
                        url=f"data:{mimeType};base64,{blob}",
                    ),
                )
            elif mimeType.startswith("audio/"):
                return pythinker_core.message.AudioURLPart(
                    type="audio_url",
                    audio_url=pythinker_core.message.AudioURLPart.AudioURL(
                        url=f"data:{mimeType};base64,{blob}"
                    ),
                )
            elif mimeType.startswith("video/"):
                return pythinker_core.message.VideoURLPart(
                    type="video_url",
                    video_url=pythinker_core.message.VideoURLPart.VideoURL(
                        url=f"data:{mimeType};base64,{blob}"
                    ),
                )

            else:
                raise ValueError(f"Unsupported mime type: {mimeType}")
        case mcp.types.ResourceLink(uri=uri, mimeType=mimeType, description=_description):
            mimeType = mimeType or "application/octet-stream"
            if mimeType.startswith("image/"):
                return pythinker_core.message.ImageURLPart(
                    type="image_url",
                    image_url=pythinker_core.message.ImageURLPart.ImageURL(url=str(uri)),
                )
            elif mimeType.startswith("audio/"):
                return pythinker_core.message.AudioURLPart(
                    type="audio_url",
                    audio_url=pythinker_core.message.AudioURLPart.AudioURL(url=str(uri)),
                )
            elif mimeType.startswith("video/"):
                return pythinker_core.message.VideoURLPart(
                    type="video_url",
                    video_url=pythinker_core.message.VideoURLPart.VideoURL(url=str(uri)),
                )
            else:
                raise ValueError(f"Unsupported mime type: {mimeType}")
        case _:
            raise ValueError(f"Unsupported MCP tool result part: {part}")
