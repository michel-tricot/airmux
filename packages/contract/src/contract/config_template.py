"""The shared airllm.yml template written by `airllmcp init`.

It lives in contract because it is the one file both planes parse: the control_plane section
through control_plane.config.Settings and the data_plane section through data_plane.config.Config.
Each plane owns a test that parses the rendered template through its real loader, so a schema or
env-var change that is not reflected here fails that plane's suite instead of drifting silently.
"""

from __future__ import annotations

DEFAULT_CONFIG_YML = """control_plane:
  database:
    url: {db_url}
  bundle:
    signing_key: env:GW_BUNDLE_SIGNING_KEY
    staleness_bound_hours: 24

data_plane:
  control_plane:
    url: {control_plane_url}
    token: env:GW_DATAPLANE_TOKEN
  bundle:
    public_key: env:GW_BUNDLE_PUBLIC_KEY
    org: {org}
    cache_dir: {cache_dir}
    staleness_policy: serve_and_warn # or refuse
    poll_interval_s: 5
  events:
    flush_interval_s: 5
"""
