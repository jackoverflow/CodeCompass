# Dev container image: Python 3.11 (backend) + Node.js 20 (frontend)
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# Fix: Remove the broken Yarn repository pre-configured in the base image
RUN rm -f /etc/apt/sources.list.d/yarn.list

# Node.js 20 LTS via NodeSource
ARG NODE_MAJOR=20
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python tooling
RUN pip install --no-cache-dir --upgrade pip

# Non-root user (created by the base image)
ARG USERNAME=vscode
USER ${USERNAME}
WORKDIR /workspaces/LivingArchitectureAndTechnicalDebtMapper