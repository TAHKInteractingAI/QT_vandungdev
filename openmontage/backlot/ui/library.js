import { el, fmtAgo, getJSON, mediaURL, subscribe, thumbURL } from "/ui/lib.js";

const grid = document.getElementById("grid");

function miniRail(states) {
  const rail = el("div", { class: "mini-rail" });
  for (const s of states) {
    const cls = s.status === "completed" ? "d"
      : s.status === "in_progress" ? "a"
      : s.status === "awaiting_human" ? "w" : "";
    rail.append(el("i", { class: cls, title: `${s.name}: ${s.status}` }));
  }
  return rail;
}

function card(p) {
  const poster = el("div", { class: "lib-poster" });
  if (p.poster) {
    poster.append(el("img", { src: thumbURL(p.project_id, p.poster, 640), loading: "lazy", alt: "" }));
  } else {
    poster.append(el("span", { class: "lp-txt" }, "NO MEDIA YET"));
  }
  if (p.live && p.active_stage) {
    poster.append(el("span", { class: "lp-live" },
      el("span", { class: "dot" }),
      p.awaiting_human ? "◈ AWAITING YOU" : `LIVE · ${p.active_stage.toUpperCase()}`));
  } else if (p.awaiting_human) {
    poster.append(el("span", { class: "lp-live" }, "◈ AWAITING YOU"));
  }

  const meta = el("div", { class: "lb-meta" },
    el("span", { class: "chip" }, p.pipeline_type || "unknown"),
    p.scene_count ? el("span", { class: "chip" }, `${p.scene_count} scenes`) : null,
    p.render_count ? el("span", { class: "chip" }, `${p.render_count} renders`) : null,
    el("span", { class: "when" }, fmtAgo(p.last_activity)),
  );

  const actions = el("div", { class: "lib-actions" });
  for (const output of p.outputs || []) {
    actions.append(el("a", {
      class: "lib-action download-action",
      href: mediaURL(p.project_id, output),
      download: output.split("/").pop(),
    }, `Download ${output.split("/").pop()}`));
  }
  if (!(p.outputs || []).length) {
    actions.append(el("span", { class: "lib-action disabled-action" }, "No output yet"));
  }
  actions.append(el("button", {
    class: "lib-action delete-action",
    type: "button",
    onclick: () => removeProject(p.project_id, p.title || p.project_id),
  }, "Delete project"));

  return el("article", { class: `lib-card${p.live ? " live-card" : ""}` },
    poster,
    el("div", { class: "lib-body" },
      el("h3", {}, (p.title || p.project_id).toUpperCase()),
      meta,
      p.stage_states.length ? miniRail(p.stage_states) : null,
      actions,
    ),
  );
}

async function removeProject(projectId, title) {
  if (!window.confirm(`Delete “${title}” and all generated files?`)) return;
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`Could not delete ${title}.`);
  await render();
}

async function render() {
  const projects = await getJSON("/api/projects");
  document.getElementById("count").textContent = `${projects.length} projects`;
  const liveCount = projects.filter((p) => p.live).length;
  const badge = document.getElementById("liveBadge");
  badge.classList.toggle("idle", liveCount === 0);
  document.getElementById("liveText").textContent = liveCount ? `${liveCount} LIVE` : "IDLE";
  grid.innerHTML = "";
  document.getElementById("empty").style.display = projects.length ? "none" : "block";
  for (const p of projects) grid.append(card(p));
}

render().catch(console.error);
if (!new URLSearchParams(location.search).has("static")) {
  subscribe("/api/library/events", () => render().catch(console.error));
}
