/* Dragon Technologies Inventory Manager - Scan Station
 * Uses jsQR (self-hosted) to decode QR codes from the webcam.
 * Flow: scan student badge -> scan asset label -> check out / return.
 */
(function () {
  "use strict";

  // --- DOM refs ------------------------------------------------------------
  var video      = document.getElementById("scan-video");
  var btnStart   = document.getElementById("btn-start");
  var btnStop    = document.getElementById("btn-stop");
  var btnReset   = document.getElementById("btn-reset");
  var btnCheckout= document.getElementById("btn-checkout");
  var btnReturn  = document.getElementById("btn-return");
  var hint       = document.getElementById("scan-hint");
  var studentBox = document.getElementById("student-box");
  var itemBox    = document.getElementById("item-box");
  var actionArea = document.getElementById("action-area");
  var resultBox  = document.getElementById("scan-result");
  var dueDays    = document.getElementById("due-days");

  // --- Session state -------------------------------------------------------
  var stream   = null;
  var scanning = false;
  var canvas   = document.createElement("canvas");
  var ctx      = canvas.getContext("2d", { willReadFrequently: true });

  var session = { student: null, item: null };
  var lastCode = "";          // de-dupe: ignore the same QR repeated each frame
  var lastCodeAt = 0;
  var busy = false;           // block overlapping API calls

  // --- Helpers -------------------------------------------------------------
  function showResult(message, kind) {
    resultBox.hidden = false;
    resultBox.textContent = message;
    resultBox.className = "scan-result scan-result-" + (kind || "info");
  }

  function clearResult() {
    resultBox.hidden = true;
    resultBox.textContent = "";
  }

  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); });
  }

  function refreshActionArea() {
    // Show action buttons only when both a student and an item are loaded.
    if (session.student && session.item) {
      actionArea.hidden = false;
      var out = session.item.status === "Checked Out";
      // If item is out, returning makes sense; if available, checkout does.
      btnCheckout.style.display = out ? "none" : "block";
      btnReturn.style.display   = out ? "block" : "none";
    } else {
      actionArea.hidden = true;
    }
  }

  // --- Resolving scans -----------------------------------------------------
  function handleCode(text) {
    if (busy) return;
    // De-dupe identical codes within a 2.5s window.
    var nowT = Date.now();
    if (text === lastCode && (nowT - lastCodeAt) < 2500) return;
    lastCode = text;
    lastCodeAt = nowT;

    if (!session.student) {
      resolveBadge(text);
    } else {
      resolveItem(text);
    }
  }

  function resolveBadge(text) {
    busy = true;
    hint.textContent = "Reading badge\u2026";
    postJSON("/api/badge", { payload: text }).then(function (res) {
      busy = false;
      if (res.ok) {
        session.student = res;
        studentBox.className = "scan-slot scan-slot-ok";
        studentBox.innerHTML =
          "<strong>" + escapeHtml(res.name) + "</strong>" +
          "<span class='mono dim'>" + escapeHtml(res.employee_id) + "</span>";
        hint.textContent = "Student loaded. Now scan an asset label.";
        clearResult();
      } else {
        // bad_payload / no_employee_id / not_in_roster / inactive
        showResult(res.message, "error");
        hint.textContent = "Badge not accepted. Try another scan.";
      }
      refreshActionArea();
    }).catch(function () {
      busy = false;
      showResult("Network error talking to the server.", "error");
    });
  }

  function resolveItem(text) {
    busy = true;
    hint.textContent = "Reading asset label\u2026";
    postJSON("/api/item-lookup", { payload: text }).then(function (res) {
      busy = false;
      if (res.ok) {
        session.item = res;
        itemBox.className = "scan-slot scan-slot-ok";
        itemBox.innerHTML =
          "<strong>" + escapeHtml(res.name) + "</strong>" +
          "<span class='mono dim'>" + escapeHtml(res.item_code) + "</span>" +
          "<span class='scan-slot-status'>" + escapeHtml(res.status) + "</span>";
        hint.textContent = "Asset loaded. Choose an action.";
        clearResult();
      } else {
        showResult(res.message, "error");
        hint.textContent = "Asset not found. Try another scan.";
      }
      refreshActionArea();
    }).catch(function () {
      busy = false;
      showResult("Network error talking to the server.", "error");
    });
  }

  // --- Actions -------------------------------------------------------------
  btnCheckout.addEventListener("click", function () {
    if (!session.student || !session.item || busy) return;
    busy = true;
    postJSON("/api/checkout", {
      item_id: session.item.item_id,
      student_id: session.student.student_id,
      days: parseInt(dueDays.value, 10),
    }).then(function (res) {
      busy = false;
      showResult(res.message, res.ok ? "success" : "error");
      if (res.ok) { session.item = null; resetItemSlot(); }
      refreshActionArea();
    }).catch(function () {
      busy = false;
      showResult("Network error during checkout.", "error");
    });
  });

  btnReturn.addEventListener("click", function () {
    if (!session.item || busy) return;
    busy = true;
    postJSON("/api/return", { item_id: session.item.item_id })
      .then(function (res) {
        busy = false;
        showResult(res.message, res.ok ? "success" : "error");
        if (res.ok) { session.item = null; resetItemSlot(); }
        refreshActionArea();
      }).catch(function () {
        busy = false;
        showResult("Network error during return.", "error");
      });
  });

  // --- Reset ---------------------------------------------------------------
  function resetItemSlot() {
    itemBox.className = "scan-slot scan-slot-empty";
    itemBox.textContent = "Waiting for asset scan\u2026";
  }

  btnReset.addEventListener("click", function () {
    session = { student: null, item: null };
    studentBox.className = "scan-slot scan-slot-empty";
    studentBox.textContent = "Waiting for badge scan\u2026";
    resetItemSlot();
    actionArea.hidden = true;
    clearResult();
    lastCode = "";
    hint.textContent = scanning ? "Scan a student badge." : "Camera is off.";
  });

  // --- Camera + decode loop ------------------------------------------------
  function tick() {
    if (!scanning) return;
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      var code = jsQR(img.data, img.width, img.height, {
        inversionAttempts: "dontInvert",
      });
      if (code && code.data) {
        handleCode(code.data.trim());
      }
    }
    requestAnimationFrame(tick);
  }

  btnStart.addEventListener("click", function () {
    navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
    }).then(function (s) {
      stream = s;
      video.srcObject = s;
      video.setAttribute("playsinline", true);
      video.play();
      scanning = true;
      btnStart.disabled = true;
      btnStop.disabled = false;
      hint.textContent = "Scan a student badge.";
      requestAnimationFrame(tick);
    }).catch(function (err) {
      hint.textContent = "Could not open camera: " + err.message;
    });
  });

  btnStop.addEventListener("click", function () {
    scanning = false;
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); }
    btnStart.disabled = false;
    btnStop.disabled = true;
    hint.textContent = "Camera is off.";
  });

  // --- Misc ----------------------------------------------------------------
  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
})();
