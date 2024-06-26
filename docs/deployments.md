---
title: Kitsune Deployments
---

This documents the current development (dev), staging and production
(prod) servers for the `support.mozilla.com` instance of
[Kitsune](https://github.com/mozilla/kitsune).

# The Source

All of the source code for Kitsune lives in [a single Github
repo](https://github.com/mozilla/kitsune).

# Branches

## main

The `main` branch is our main integration points. All new patches should
be based on the latest `main` (or rebased to it).

Pull requests are created from those branches. Pull requests may be
opened at any time, including before any code has been written.

Pull requests get reviewed.

Once reviewed, the branch is merged into `main`, except in special cases
such as changes that require re-indexing. See
[Changes that involve reindexing](development.md#changes-that-involve-reindexing).

We deploy to production from `main`.

# Deploying

For our infrastructure instructions see [Kubernetes Support Guide](k8s.md).

# Servers

## Development

<https://support-dev.allizom.org/>

We use dev primarily to develop infrastructure changes.

## Staging

<https://support.allizom.org/>

We deploy to stage anything we want to test including deployments
themselves.

## Production

<https://support.mozilla.org/>
