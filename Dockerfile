# ReceiptGate — the obligation ledger.
#
# Build context is the STACK ROOT, not this repository, because the image must
# install the canonical protocol package from the sibling LegiVellum checkout:
#
#     docker build -f ReceiptGate/Dockerfile .
#
# That is deliberate. Previously ReceiptGate had no Dockerfile at all and the
# demo stack ran it as `pip install` into a bare python:3.11-slim with the repo
# bind-mounted, so the workflow written to catch container bugs could not catch
# ReceiptGate's. Worse, nothing installed `legivellum`; components resolved it
# by walking parent directories for a source tree that does not exist in an
# image, and fell back to posting unvalidated receipts.
#
# Installing the protocol package explicitly is the point: if it is missing,
# the build fails here rather than the ledger silently accepting anything.

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# The canonical protocol package first: receipt models, validation, and the
# schema itself, which ships as package data so validation works with no
# repository checkout present.
COPY LegiVellum/pyproject.toml LegiVellum/README.md /src/LegiVellum/
COPY LegiVellum/shared/ /src/LegiVellum/shared/
RUN pip install --no-cache-dir /src/LegiVellum

COPY ReceiptGate/pyproject.toml ReceiptGate/README.md /src/ReceiptGate/
COPY ReceiptGate/src/ /src/ReceiptGate/src/
COPY ReceiptGate/schema/ /src/ReceiptGate/schema/
RUN pip install --no-cache-dir /src/ReceiptGate

# Fail the build if the ledger cannot validate a receipt. This is the Phase 0
# exit condition, asserted at build time as well as in the test suite: an image
# that cannot import the validator must not be publishable.
RUN python -c "\
import legivellum.validation as v; \
p = v.schema_path(); \
assert p.exists(), p; \
print('receipt schema resolved at', p)"

RUN addgroup --system --gid 1001 receiptgate \
    && adduser --system --uid 1001 --gid 1001 receiptgate \
    && mkdir -p /data && chown -R receiptgate:receiptgate /app /data

USER receiptgate

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json, os, urllib.request; \
url=os.environ.get('RECEIPTGATE_MCP_URL','http://localhost:8000/mcp'); \
payload={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'receiptgate.health','arguments':{}}}; \
req=urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}); \
token=os.environ.get('RECEIPTGATE_API_KEY'); \
token and req.add_header('Authorization','Bearer '+token); \
data=json.load(urllib.request.urlopen(req, timeout=5)); \
assert 'result' in data"

CMD ["receiptgate"]
