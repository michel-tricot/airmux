from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.egress.base import UpstreamRequest, encode
from data_plane.egress.openai_compatible import OpenAICompatibleAdapter
from data_plane.formats.openai import body_of

if TYPE_CHECKING:
    from contract import ModelEntry
    from data_plane.canonical import CanonicalRequest


class AwsBedrockAdapter(OpenAICompatibleAdapter):
    kind = "aws_bedrock"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        headers = {"authorization": f"Bearer {self.credential.reveal()}", "content-type": "application/json"}
        url = str(self.provider.base_url).rstrip("/") + "/chat/completions"
        body = encode(body_of(req, m.upstream_model), aliases={"max_output_tokens": "max_tokens", **self.provider.param_aliases}, extras=req.extra)
        return UpstreamRequest(method="POST", url=url, headers=headers, body=body)
