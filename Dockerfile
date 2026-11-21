# Base images come from the AWS mirror of the official Docker images: Docker Hub rate-limits shared builders such as Railway's.
# Stage 1: build the web app
FROM public.ecr.aws/docker/library/node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: the Python service, serving the built web app too
FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
# The pinned model gets the first layer, so dependency, code and pack changes do not download it again.
COPY server/scripts/fetch_model.py ./server/scripts/fetch_model.py
RUN cd server && python scripts/fetch_model.py --out models/dinov2-small-int8.onnx
RUN pip install --no-cache-dir uv
COPY server/pyproject.toml server/uv.lock ./server/
RUN cd server && uv export --locked --no-dev --no-hashes -o requirements.txt && uv pip install --system -r requirements.txt
COPY server/ ./server/
COPY packs/ ./packs/
COPY --from=web /web/dist ./web/dist
ENV PACK_DIR=/srv/packs/burrell-pilot MODEL_PATH=/srv/server/models/dinov2-small-int8.onnx WEB_DIST=/srv/web/dist
WORKDIR /srv/server
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --ws-max-size 1048576 --no-access-log"]
