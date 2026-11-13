// SPDX-License-Identifier: AGPL-3.0-or-later
// "Check a credential" page: posts the chosen file to /api/v1/verify and shows the result.
(function () {
  "use strict";
  var form = document.getElementById("check-form");
  var out = document.getElementById("out");
  function el(tag, text) { var e = document.createElement(tag); if (text) e.textContent = text; return e; }
  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var file = document.getElementById("file").files[0];
    out.textContent = "";
    if (!file) { out.appendChild(el("p", "Choose a credential file first.")); return; }
    out.appendChild(el("p", "Checking…"));
    file.text().then(function (body) {
      return fetch("/api/v1/verify", { method: "POST", body: body,
        headers: { "content-type": "application/json" } });
    }).then(function (res) { return res.json().then(function (j) { return [res.ok, j]; }); })
    .then(function (pair) {
      out.textContent = "";
      var j = pair[1];
      if (!pair[0]) { out.appendChild(el("p", j.detail || j.title || "That file could not be checked.")); return; }
      out.appendChild(el("h2", "Result: " + j.label));
      if (j.achievement && j.achievement.name) out.appendChild(el("p", "Credential: " + j.achievement.name));
      if (j.issuer && j.issuer.name) out.appendChild(el("p", "Issuer: " + j.issuer.name));
      var ul = el("ul");
      (j.checks || []).forEach(function (c) { ul.appendChild(el("li", c.name + ": " + c.status + ". " + c.detail)); });
      out.appendChild(ul);
      out.appendChild(el("p", j.explanation || ""));
    }).catch(function () {
      out.textContent = "";
      out.appendChild(el("p", "The check could not be completed. This is not evidence that anything is wrong; please try again."));
    });
  });
})();
