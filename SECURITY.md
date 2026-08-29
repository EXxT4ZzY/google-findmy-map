# Security

## The service has no authentication — put it behind an authenticating proxy

`findmy-map` exposes the **full location history** of your devices and the
**addresses they visited**, and lets any caller rename devices or trigger
polls. It has **no login, no API key, no access control of any kind**.

Anyone who can reach the HTTP port can see everywhere your devices have been.

**You must run it behind a reverse proxy that enforces authentication**
(HTTP Basic auth, an OAuth2 proxy such as `oauth2-proxy`, Authelia,
Cloudflare Access, Tailscale, a VPN, …). The provided `docker-compose.yml`
publishes **no ports** and attaches the container only to an external
`proxy-net` network for exactly this reason — do not add a `ports:` mapping
that exposes it directly.

Treat the database at `${GFM_DATA_DIR}/history.db` as sensitive personal
data. Back it up and store it accordingly.

## Defence-in-depth measures built into the app

These do **not** replace the reverse-proxy authentication above.

- **Cross-site request blocking.** `POST /api/refresh` and
  `PUT /api/devices/{id}` reject requests whose `Sec-Fetch-Site` header is
  `cross-site`/`same-site` (Fetch Metadata). This stops a random web page
  the operator visits from triggering polls or edits. Non-browser clients
  (curl, scripts) send no such header and are unaffected.
- **Input validation.** Pin colours (from the API and from
  `GFM_DEVICE_COLORS`) must be a plain hex value or CSS colour keyword; SQL
  is fully parameterised; device names are HTML-escaped in the frontend.
- **Reverse-geocoding rate limiting.** The background geocoder makes at
  most one request every ~1.1 s to the configured Nominatim endpoint,
  negatively caches failed lookups, and backs off exponentially on
  repeated failures — so an outage can't turn into a request flood that
  gets your IP blocked by the public OSM Nominatim.
- **Non-root container.** The service runs as an unprivileged UID
  (`${PUID}:${PGID}`).

## Supply chain

The Docker image `git clone`s
[`leonboe1/GoogleFindMyTools`](https://github.com/leonboe1/GoogleFindMyTools)
at build time (`ARG GFM_UPSTREAM_REF` in the `Dockerfile`), pinned to a
specific commit SHA. You are trusting that
upstream project (and its dependency tree, which includes Selenium /
undetected-chromedriver even though no browser is launched at runtime).
Review the pinned commit before building, and bump it deliberately.

## Reporting a vulnerability

Open a private security advisory on the repository, or an issue if the
project has no advisory support. Please do not include working exploit
code in a public issue.
