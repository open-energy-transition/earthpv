---
title: Blog
description: >-
  Updates, method notes and field reports from the EarthPV / TraceTheSun team.
hide:
  - toc
---

# Blog

Updates, method notes and field reports from the people building EarthPV and the
wider **TraceTheSun** pilot. Posts here are informal by design: what a
recalibration changed and why, what a week of quadrat mapping in Pakistan turned
up, where a method broke. The settled version of anything below lives under
[How it works](../how-it-works.md); the dated register of every experiment is
[Experiments](../experiments.md).

!!! tip "Want to publish a post here?"

    The blog is open to contributions. Posts are plain Markdown files under
    `docs/blog/posts/` in the repository.

    - **Preferred:** open a pull request against
      [open-energy-transition/earthpv](https://github.com/open-energy-transition/earthpv)
      adding your post file (see [How to add a post](#how-to-add-a-post) below).
    - **Or get in touch first:** open an
      [issue](https://github.com/open-energy-transition/earthpv/issues) describing
      what you want to write, or reach the team through the
      [Community](../index.md#community) contacts. We are happy to co-author or to
      publish a guest post on your behalf.

## How to add a post

1. Create `docs/blog/posts/YYYY-MM-DD-your-slug.md`.
2. Give it front matter with at least a `date`, plus optional `authors` and
   `categories`:

    ```yaml
    ---
    date: 2026-09-01
    authors:
      - earthpv
    categories:
      - Method notes
    ---

    # Your post title

    One or two sentences of intro that stand alone as the excerpt.

    <!-- more -->

    The rest of the post.
    ```

3. If you want a byline of your own, add yourself to `docs/blog/.authors.yml`
   and reference that key under `authors`.
4. Allowed `categories` are declared in `mkdocs.yml` (`Announcements`,
   `Method notes`, `Field reports`, `Results`, `Perspectives`) -- add a new one
   there in the same PR if you need it.
5. Preview locally with `pixi run -e docs docs-serve`. CI builds the site with
   `mkdocs build --strict`, so a bad link or an undeclared category fails the
   build.
