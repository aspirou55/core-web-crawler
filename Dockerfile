# Recipe for the crawler service image. Build:  docker build -t crawler-api .
#                                        Run:    docker run -p 8000:8000 crawler-api

# Start from an official base image: Debian Linux + Python 3.12 preinstalled.
# "slim" = trimmed of compilers/docs we don't need (smaller = faster deploys).
# Pinning the version means the image builds the same way next year.
FROM python:3.12-slim

# All following commands run from this directory inside the image.
WORKDIR /app

# Copy ONLY the dependency list first, then install. Docker caches each step:
# as long as requirements.txt is unchanged, rebuilds skip the slow pip install
# and jump straight to copying code. (Code changes daily; deps change rarely —
# so copy the rarely-changing thing first.)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now the actual application code.
COPY crawler/ ./crawler/

# Don't run as root inside the container: if a bug ever let an attacker
# execute code in our service, they land in an unprivileged account.
RUN useradd --create-home appuser
USER appuser

# Documentation for humans and platforms: this service listens on port 8000.
EXPOSE 8000

# What runs when a container starts. --host 0.0.0.0 is REQUIRED here:
# inside the container, 127.0.0.1 would mean "the container itself" and
# nothing outside it — not even your own laptop — could ever connect.
# 0.0.0.0 means "accept connections arriving from outside the container";
# the cloud platform (or your -p flag) controls who can actually reach it.
CMD ["python", "-m", "uvicorn", "crawler.api:app", "--host", "0.0.0.0", "--port", "8000"]
