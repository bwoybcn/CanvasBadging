// SPDX-License-Identifier: AGPL-3.0-or-later
// "Check a credential file" page: posts the chosen file to /api/v1/verify and shows the result.
// The reader is usually an employer or admissions officer, not a developer: the verdict comes
// first in plain words, and the technical checks stay folded away, as on a shared badge page.
(function () {
  "use strict";
  var form = document.getElementById("check-form");
  var out = document.getElementById("out");
  var words = JSON.parse(document.getElementById("result-words").textContent);
  function el(tag, text) { var e = document.createElement(tag); if (text) e.textContent = text; return e; }
  function say(text) { out.textContent = ""; out.appendChild(el("p", text)); }
  // Errors from the API are written for developers ("The request body must be…"); say what to do.
  var REFUSALS = {
    NOT_JSON: "This is not a credential file. Choose the .json file downloaded from the badge page (Download credential file).",
    TOO_LARGE: "This file is too large to be a credential file. Choose the .json file downloaded from the badge page."
  };
  function checkName(name) { var s = name.replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var file = document.getElementById("file").files[0];
    if (!file) { say("Choose a credential file first."); return; }
    say("Checking…");
    file.text().then(function (body) {
      return fetch("/api/v1/verify", { method: "POST", body: body,
        headers: { "content-type": "application/json" } });
    }).then(function (res) { return res.json().then(function (j) { return [res.ok, j]; }); })
    .then(function (pair) {
      var j = pair[1];
      if (!pair[0]) { say(REFUSALS[j.code] || "That file could not be checked. Choose the .json file downloaded from the badge page."); return; }
      out.textContent = "";
      var style = words.style[j.result] || words.style.unable_to_verify;
      var box = el("section");
      box.className = "result";
      box.style.borderColor = style[0];
      var h = el("h2");
      var mark = el("span", style[1] + " ");
      mark.setAttribute("aria-hidden", "true");
      mark.style.color = style[0];
      h.appendChild(mark);
      h.appendChild(el("strong", j.label));
      box.appendChild(h);
      box.appendChild(el("p", words.text[j.result] || ""));
      var name = j.achievement && j.achievement.name;
      var issuer = j.issuer && j.issuer.name;
      if (name || issuer) {
        var dl = el("dl");
        if (name) { dl.appendChild(el("dt", "Badge")); dl.appendChild(el("dd", name)); }
        if (issuer) { dl.appendChild(el("dt", "Issued by")); dl.appendChild(el("dd", issuer)); }
        box.appendChild(dl);
        if (j.result !== "verified") {
          box.appendChild(el("p", "These details are what the file says. Because the check did not pass, do not rely on them.")).className = "muted";
        }
      }
      var details = el("details");
      details.appendChild(el("summary", "Show the individual checks"));
      var ul = el("ul");
      (j.checks || []).forEach(function (c) {
        var li = el("li");
        li.appendChild(el("strong", checkName(c.name)));
        li.appendChild(document.createTextNode(": " + c.status + ". " + c.detail));
        ul.appendChild(li);
      });
      details.appendChild(ul);
      box.appendChild(details);
      out.appendChild(box);
    }).catch(function () {
      say("The check could not be completed. This is not evidence that anything is wrong; please try again.");
    });
  });
})();
