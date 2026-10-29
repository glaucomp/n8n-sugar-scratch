#!/usr/bin/env python3
"""Copy the influencer template, key the clip, and write the received name and id.

Greenkey runs before After Effects. After Effects stores footage paths inside
the project file. This script writes a JSX file the workflow runs so After
Effects opens the copy and relinks footage.
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

DATA_RELATIVE = "(Footage)/influencer/data.json"
ALPHA_RELATIVE = "(Footage)/influencer/influencer_alpha.mov"
REMOTE_GREENKEY = "https://greenkey.mxjprod.work"
TOKEN_FILE = os.path.expanduser("~/Desktop/PackageMaker/api_token")
USER_FILE = os.path.expanduser("~/Desktop/PackageMaker/api_user")
POLL_LIMIT_SECONDS = 60 * 60
# Cloudflare error 1010 blocks the default Python client name.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

JSX = r"""(function () {
  // Relink copied footage so the project reads the edited data file.
  var projectPath = __PROJECT_PATH__;
  var files = __FILES__;
  var personName = __NAME__;
  var cardId = __ID__;
  var alphaPath = __ALPHA_PATH__;
  var lineBreak = String.fromCharCode(10);

  function normalize(value) {
    var text = String(value).toLowerCase();
    while (text.length > 1 && text.charAt(text.length - 1) === "/") {
      text = text.substring(0, text.length - 1);
    }
    return text;
  }

  function samePath(left, right) {
    if (!left || !right) {
      return false;
    }
    return normalize(left) === normalize(right);
  }

  function scriptFile(path) {
    return new File(encodeURI(path));
  }

  var projectFile = scriptFile(projectPath);
  if (!projectFile.exists) {
    alert("Project file not found:" + lineBreak + projectPath);
    return;
  }

  app.beginUndoGroup("Relink footage");
  var opened = null;
  try {
    if (app.project && app.project.file && samePath(app.project.file.fsName, projectPath)) {
      opened = app.project;
    } else {
      opened = app.open(projectFile);
    }
  } catch (openError) {
    app.endUndoGroup();
    alert("After Effects did not open the project:" + lineBreak + projectPath + lineBreak + openError.toString());
    return;
  }
  if (!opened) {
    app.endUndoGroup();
    alert("After Effects did not open the project:" + lineBreak + projectPath);
    return;
  }

  var missing = [];
  var relinked = 0;
  var baseCount = {};
  var index;
  for (index = 0; index < files.length; index++) {
    var baseKey = String(files[index].oldBasename).toLowerCase();
    if (baseCount[baseKey] === undefined) {
      baseCount[baseKey] = 0;
    }
    baseCount[baseKey] = baseCount[baseKey] + 1;
  }

  var itemIndex;
  for (itemIndex = 1; itemIndex <= app.project.numItems; itemIndex++) {
    var item = app.project.item(itemIndex);
    if (!item || item.typeName !== "Footage" || !item.file) {
      continue;
    }
    var stored = item.file.fsName;
    var baseName = item.file.name;
    var row = null;
    var fileIndex;
    for (fileIndex = 0; fileIndex < files.length; fileIndex++) {
      if (samePath(stored, files[fileIndex].sourceAbsolute) || samePath(stored, files[fileIndex].oldAbsolute)) {
        row = files[fileIndex];
        break;
      }
    }
    if (!row) {
      var baseKeyMatch = String(baseName).toLowerCase();
      if (baseCount[baseKeyMatch] === 1) {
        for (fileIndex = 0; fileIndex < files.length; fileIndex++) {
          if (String(files[fileIndex].oldBasename).toLowerCase() === baseKeyMatch) {
            row = files[fileIndex];
            break;
          }
        }
      }
    }
    if (!row) {
      missing.push(item.name + " (" + stored + ")");
      continue;
    }
    var target = scriptFile(row.newAbsolute);
    if (!target.exists) {
      missing.push(item.name + " missing file " + row.newAbsolute);
      continue;
    }
    try {
      item.replace(target);
      relinked = relinked + 1;
    } catch (replaceError) {
      missing.push(item.name + ": " + replaceError.toString());
    }
  }

  function clearKeys(prop) {
    if (!prop) {
      return;
    }
    if (prop.expressionEnabled) {
      prop.expressionEnabled = false;
    }
    while (prop.numKeys > 0) {
      prop.removeKey(1);
    }
  }

  function setXY(prop, x, y) {
    var current = prop.value;
    if (current.length > 2) {
      prop.setValue([x, y, current[2]]);
    } else {
      prop.setValue([x, y]);
    }
  }

  function layerBox(layer) {
    var rect = layer.sourceRectAtTime(0, false);
    var scale = layer.property("Scale").value;
    var pos = layer.property("Position").value;
    var anchor = layer.property("Anchor Point").value;
    var sx = scale[0] / 100;
    var sy = scale[1] / 100;
    return {
      left: pos[0] + (rect.left - anchor[0]) * sx,
      top: pos[1] + (rect.top - anchor[1]) * sy,
      width: rect.width * Math.abs(sx),
      height: rect.height * Math.abs(sy)
    };
  }

  function fitLayer(videoLayer, box) {
    var source = videoLayer.source;
    if (!source || source.width < 2 || source.height < 2) {
      return false;
    }
    if (!box || box.width < 2 || box.height < 2) {
      return false;
    }
    var srcW = source.width;
    var srcH = source.height;
    // Sit inside the placement, smaller than the window, with the top of the
    // clip under the top of that window so the card title stays visible.
    var fitPortion = 0.7;
    var scale = Math.min(box.width / srcW, box.height / srcH) * fitPortion * 100;
    var anchorProp = videoLayer.property("Anchor Point");
    var positionProp = videoLayer.property("Position");
    var scaleProp = videoLayer.property("Scale");
    clearKeys(anchorProp);
    clearKeys(positionProp);
    clearKeys(scaleProp);
    setXY(anchorProp, srcW / 2, srcH / 2);
    var scaleCurrent = scaleProp.value;
    if (scaleCurrent.length > 2) {
      scaleProp.setValue([scale, scale, scaleCurrent[2]]);
    } else {
      scaleProp.setValue([scale, scale]);
    }
    var fittedHeight = srcH * scale / 100;
    setXY(positionProp, box.left + box.width / 2, box.top + fittedHeight / 2);
    return true;
  }

  var fitted = 0;
  var fitNote = "";
  try {
    var compIndex;
    for (compIndex = 1; compIndex <= app.project.numItems; compIndex++) {
      var compItem = app.project.item(compIndex);
      if (!compItem || !(compItem instanceof CompItem)) {
        continue;
      }
      var placementLayer = null;
      var layerIndex;
      for (layerIndex = 1; layerIndex <= compItem.numLayers; layerIndex++) {
        var namedLayer = compItem.layer(layerIndex);
        if (namedLayer && String(namedLayer.name).toLowerCase() === "placement") {
          placementLayer = namedLayer;
          break;
        }
      }
      for (layerIndex = 1; layerIndex <= compItem.numLayers; layerIndex++) {
        var videoLayer = compItem.layer(layerIndex);
        if (!videoLayer || !(videoLayer instanceof AVLayer) || !videoLayer.source || !videoLayer.source.file) {
          continue;
        }
        if (!samePath(videoLayer.source.file.fsName, alphaPath)) {
          continue;
        }
        var box = placementLayer ? layerBox(placementLayer) : null;
        if (!box || box.width < 2 || box.height < 2) {
          box = { left: 0, top: 0, width: compItem.width, height: compItem.height };
        }
        if (fitLayer(videoLayer, box)) {
          fitted = fitted + 1;
          if (compItem.openInViewer) {
            compItem.openInViewer();
          }
        }
      }
    }
  } catch (fitError) {
    fitNote = "Could not fit the video: " + fitError.toString();
  }

  app.project.save();
  app.endUndoGroup();

  var message = "Saved " + personName + " (" + cardId + ").";
  if (relinked === 0 && missing.length === 0) {
    message += lineBreak + "No footage files were found in the project.";
  } else {
    message += lineBreak + "Relinked " + relinked + " footage item(s).";
  }
  if (fitted > 0) {
    message += lineBreak + "Fitted the video inside the frame.";
  }
  if (fitNote) {
    message += lineBreak + fitNote;
  }
  if (missing.length > 0) {
    message += lineBreak + lineBreak + "Not relinked:";
    var shown = missing.length;
    if (shown > 20) {
      shown = 20;
    }
    var missingIndex;
    for (missingIndex = 0; missingIndex < shown; missingIndex++) {
      message += lineBreak + missing[missingIndex];
    }
    if (missing.length > shown) {
      message += lineBreak + "... and " + (missing.length - shown) + " more";
    }
  }

  var alphaItem = null;
  var viewIndex;
  for (viewIndex = 1; viewIndex <= app.project.numItems; viewIndex++) {
    var viewItem = app.project.item(viewIndex);
    if (viewItem && viewItem.file && samePath(viewItem.file.fsName, alphaPath)) {
      alphaItem = viewItem;
      break;
    }
  }
  if (!alphaItem) {
    var alphaFile = scriptFile(alphaPath);
    if (alphaFile.exists) {
      alphaItem = app.project.importFile(new ImportOptions(alphaFile));
    }
  }
  if (alphaItem && alphaItem.openInViewer) {
    alphaItem.openInViewer();
  }

  var resultPath = projectFile.parent.fsName + "/ae-relink-result.txt";
  var resultFile = new File(resultPath);
  resultFile.encoding = "UTF-8";
  if (resultFile.open("w")) {
    resultFile.write(message);
    resultFile.close();
  }
})();
"""


class JobError(Exception):
    pass


def fail(message: str) -> None:
    raise JobError(message)


def clean_text(value: str, label: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        fail(label + " is empty.")
    if any(ord(char) < 32 for char in text):
        fail(label + " contains a line break or a control character.")
    if len(text) > 200:
        fail(label + " is longer than 200 characters.")
    return text


def folder_part(value: str, label: str) -> str:
    if any(char in value for char in "/\\|"):
        fail(label + " cannot contain / \\ or |.")
    if value in (".", ".."):
        fail(label + " cannot be a folder path.")
    return value


def ensure_jobs(path: str) -> str:
    if os.path.isdir(path):
        return os.path.realpath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        fail("Jobs folder parent does not exist: " + parent)
    os.makedirs(path)
    return os.path.realpath(path)


def real_dir(path: str, label: str) -> str:
    if not os.path.isdir(path):
        fail(label + " does not exist: " + path)
    return os.path.realpath(path)


def is_inside(child: str, parent: str) -> bool:
    child_path = child.rstrip("/") + "/"
    parent_path = parent.rstrip("/") + "/"
    return child_path.startswith(parent_path)


def remove_created(path: str, template: str) -> None:
    real_path = os.path.realpath(path) if os.path.exists(path) else path
    if os.path.isdir(path) and real_path != template:
        shutil.rmtree(path)


def collect_files(template: str, dest: str, project_relative: str) -> tuple[dict, list]:
    records = []
    for root, dir_names, file_names in os.walk(dest):
        dir_names.sort()
        for file_name in sorted(file_names):
            if file_name.startswith("."):
                continue
            absolute = os.path.join(root, file_name)
            if not os.path.isfile(absolute):
                continue
            relative = os.path.relpath(absolute, dest).replace("\\", "/")
            records.append(
                {
                    "oldBasename": file_name,
                    "oldRelative": relative,
                    "oldAbsolute": absolute,
                    "sourceAbsolute": os.path.normpath(os.path.join(template, relative)),
                    "newAbsolute": absolute,
                }
            )

    matches = [record for record in records if record["oldRelative"] == project_relative]
    if not matches:
        matches = [record for record in records if record["oldBasename"] == os.path.basename(project_relative)]
    if len(matches) != 1:
        found = ", ".join(record["oldRelative"] for record in records if record["oldBasename"].lower().endswith(".aep"))
        fail("Project file not found in the copy: " + project_relative + ". AEP files: " + (found or "(none)"))

    project = matches[0]
    footage = [record for record in records if record is not project]
    return project, footage


def edit_data(data_path: str, name: str, card_id: str) -> None:
    try:
        with open(data_path, encoding="utf-8") as data_file:
            data = json.load(data_file)
    except json.JSONDecodeError:
        fail("Data file is not valid JSON: " + data_path)
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, dict):
        fail("Data file has no text object: " + data_path)
    if "InfluencerName" not in text or "cardNumberText" not in text:
        fail("Data file is missing InfluencerName or cardNumberText: " + data_path)
    text["InfluencerName"] = name
    text["cardNumberText"] = card_id
    with open(data_path, "w", encoding="utf-8") as data_file:
        json.dump(data, data_file, indent=2, ensure_ascii=False)
        data_file.write("\n")


def write_jsx(dest: str, project_path: str, footage: list, name: str, card_id: str, alpha_path: str) -> str:
    jsx = (
        JSX.replace("__PROJECT_PATH__", json.dumps(project_path))
        .replace("__FILES__", json.dumps(footage))
        .replace("__NAME__", json.dumps(name))
        .replace("__ID__", json.dumps(card_id))
        .replace("__ALPHA_PATH__", json.dumps(alpha_path))
    )
    jsx_path = os.path.join(dest, "ae-relink.jsx")
    with open(jsx_path, "w", encoding="utf-8-sig") as jsx_file:
        jsx_file.write(jsx)
    return jsx_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy an After Effects template, key a clip, and write a name and an id.")
    parser.add_argument("--template", required=True)
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--clip", required=True)
    return parser.parse_args()


def clip_file(path: str) -> str:
    if not path or not os.path.isfile(path):
        fail("Clip file not found: " + str(path))
    real = os.path.realpath(path)
    if os.path.splitext(real)[1].lower() not in (".mp4", ".mov"):
        fail("Clip file must be an mp4 or a mov.")
    return real


class LoginAwareRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if is_login_page(newurl, b""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), LoginAwareRedirect)


OPENER = make_opener()


def load_token() -> str:
    token = os.environ.get("GREENKEY_TOKEN", "").strip()
    if not token and os.path.isfile(TOKEN_FILE):
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token.strip().strip('"').strip("'")


def safe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def is_login_page(location: str, body: bytes) -> bool:
    text = (location + "\n" + body[:800].decode("utf-8", "replace")).lower()
    return "authentik" in text or "outpost.goauthentik.io" in text or "<html" in text


def load_user() -> str:
    user = os.environ.get("GREENKEY_USER", "").strip()
    if not user and os.path.isfile(USER_FILE):
        user = open(USER_FILE, encoding="utf-8").read().strip()
    return user or "Glauco"


def fail_login() -> None:
    fail(
        "Greenkey showed the login page. "
        + "The key must be an Authentik app password, not an API token. "
        + "The username in ~/Desktop/PackageMaker/api_user is " + load_user() + "."
    )


def auth_headers(token: str) -> dict[str, str]:
    headers = {"User-Agent": BROWSER_USER_AGENT}
    if not token:
        return headers
    # Authentik's proxy accepts an app password as HTTP Basic, not as a Bearer token.
    credentials = base64.b64encode((load_user() + ":" + token).encode("utf-8")).decode("ascii")
    headers["Authorization"] = "Basic " + credentials
    return headers


def job_record(payload: object) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("job"), dict):
        return payload["job"]
    if isinstance(payload, dict):
        return payload
    fail("Greenkey returned a response this script cannot read.")
    return {}


def job_identifier(payload: dict) -> str:
    for key in ("id", "job_id", "jobId"):
        value = payload.get(key)
        if value:
            return str(value)
    fail("Greenkey did not return a job id.")
    return ""


def request_json(method: str, url: str, body: bytes | None, headers: dict[str, str], token: str = "", timeout: int = 120) -> dict:
    del token
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        location = error.headers.get("Location") or ""
        if error.code in (301, 302, 303, 307, 308) or is_login_page(location, raw):
            fail_login()
        detail = raw.decode("utf-8", "replace")[:300].strip()
        fail("Greenkey returned HTTP " + str(error.code) + " from " + safe_url(url) + ("." if not detail else ". " + detail))
    if is_login_page("", raw):
        fail_login()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        fail("Greenkey did not return JSON from " + safe_url(url) + ".")
    return job_record(parsed)


def submit_local(base: str, clip: str) -> str:
    payload = json.dumps({"path": clip}).encode("utf-8")
    job = request_json(
        "POST",
        base.rstrip("/") + "/jobs",
        payload,
        {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": BROWSER_USER_AGENT},
    )
    return job_identifier(job)


def submit_remote(base: str, clip: str, token: str) -> str:
    boundary = "----greenkey" + os.urandom(8).hex()
    filename = os.path.basename(clip).replace('"', "")
    with open(clip, "rb") as clip_file_handle:
        content = clip_file_handle.read()
    body = b"".join(
        [
            ("--" + boundary + "\r\n").encode("utf-8"),
            ('Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n').encode("utf-8"),
            b"Content-Type: application/octet-stream\r\n\r\n",
            content,
            ("\r\n--" + boundary + "--\r\n").encode("utf-8"),
        ]
    )
    job = request_json(
        "POST",
        base.rstrip("/") + "/jobs",
        body,
        {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            **auth_headers(token),
        },
        token,
    )
    return job_identifier(job)


def download_output(url: str, dest: str, token: str) -> None:
    headers = {"Accept": "application/octet-stream", **auth_headers(token)}
    request = urllib.request.Request(url, data=None, headers=headers, method="GET")
    try:
        with OPENER.open(request, timeout=600) as response, open(dest, "wb") as dest_file:
            shutil.copyfileobj(response, dest_file)
    except urllib.error.HTTPError as error:
        location = error.headers.get("Location") or ""
        body = error.read(400)
        if error.code in (301, 302, 303, 307, 308) or is_login_page(location, body):
            fail_login()
        fail("Greenkey did not return the alpha file. HTTP " + str(error.code) + ".")
    if os.path.getsize(dest) == 0:
        fail("Greenkey returned an empty alpha file.")
    with open(dest, "rb") as saved:
        if is_login_page("", saved.read(400)):
            os.remove(dest)
            fail_login()


def output_file(job: dict, base: str, job_id: str, token: str) -> tuple[str, bool]:
    output = job.get("output")
    if isinstance(output, dict):
        output = output.get("path") or output.get("url") or ""
    if isinstance(output, str) and os.path.isfile(output):
        return output, False
    download_url = output if isinstance(output, str) and output.startswith("http") else base.rstrip("/") + "/jobs/" + job_id + "/download"
    handle = tempfile.NamedTemporaryFile(prefix="greenkey-", suffix=".mov", delete=False)
    handle.close()
    try:
        download_output(download_url, handle.name, token)
    except Exception:
        if os.path.isfile(handle.name):
            os.remove(handle.name)
        raise
    return handle.name, True


def wait_for_greenkey(base: str, job_id: str, token: str) -> tuple[str, bool]:
    global OPENER
    started = time.time()
    poll_seconds = float(os.environ.get("GREENKEY_POLL_SECONDS", "3"))
    previous = ""
    misses = 0
    while True:
        try:
            job = request_json(
                "GET",
                base.rstrip("/") + "/jobs/" + job_id,
                None,
                {"Accept": "application/json", **auth_headers(token)},
                token,
                45,
            )
            misses = 0
        except (urllib.error.URLError, TimeoutError):
            misses += 1
            print("Greenkey: the status check timed out. Trying again.", flush=True)
            OPENER = make_opener()
            if misses >= 5:
                fail("Greenkey stopped answering after the job was submitted. Run the form again when the site responds.")
            time.sleep(max(poll_seconds, 5))
            continue
        status = str(job.get("status") or job.get("state") or "").lower()
        progress = job.get("progress")
        step = job.get("step") or ""
        line = "Greenkey: " + (status or "waiting")
        if step:
            line += " " + str(step)
        if progress is not None and progress != "":
            line += " " + str(progress)
        if line != previous:
            print(line, flush=True)
            previous = line
        if status in ("succeeded", "success", "completed", "done"):
            return output_file(job, base, job_id, token)
        if status in ("failed", "error", "cancelled", "canceled"):
            detail = job.get("error") or job.get("detail") or job.get("message") or status
            fail("Greenkey failed. " + str(detail))
        if time.time() - started > POLL_LIMIT_SECONDS:
            fail("Greenkey did not finish within 60 minutes.")
        time.sleep(poll_seconds)


def uses_local_path(base: str) -> bool:
    if os.environ.get("GREENKEY_FORCE_UPLOAD") == "1":
        return False
    return base.startswith("http://127.0.0.1") or base.startswith("http://localhost")


def key_clip(clip: str) -> tuple[str, bool]:
    global OPENER
    OPENER = make_opener()
    base = os.environ.get("GREENKEY_URL", REMOTE_GREENKEY).rstrip("/")
    token = load_token()
    print("Greenkey: uploading to " + base, flush=True)
    try:
        if uses_local_path(base):
            job_id = submit_local(base, clip)
        else:
            job_id = submit_remote(base, clip, token)
    except urllib.error.URLError as error:
        fail("Greenkey could not be reached at " + base + ". " + str(error.reason))
    print("Greenkey job " + job_id, flush=True)
    return wait_for_greenkey(base, job_id, token)


def place_alpha(dest: str, alpha_path: str, owns_alpha: bool) -> str:
    folder = os.path.join(dest, "(Footage)", "influencer")
    os.makedirs(folder, exist_ok=True)
    # After Effects looks up this file name inside the copied project.
    final_path = os.path.join(folder, "influencer_alpha.mov")
    shutil.copy2(alpha_path, final_path)
    if owns_alpha and os.path.realpath(alpha_path) != os.path.realpath(final_path):
        os.remove(alpha_path)
    return final_path


def point_alpha_at(footage: list, template: str, dest: str, final_path: str) -> None:
    source_absolute = os.path.normpath(os.path.join(template, ALPHA_RELATIVE))
    old_absolute = os.path.normpath(os.path.join(dest, ALPHA_RELATIVE))
    for record in footage:
        if record.get("oldBasename") == "influencer_alpha.mov" or record.get("oldRelative") == ALPHA_RELATIVE:
            record["oldBasename"] = "influencer_alpha.mov"
            record["oldRelative"] = ALPHA_RELATIVE
            record["sourceAbsolute"] = source_absolute
            record["oldAbsolute"] = old_absolute
            record["newAbsolute"] = final_path
            return
    footage.append(
        {
            "oldBasename": "influencer_alpha.mov",
            "oldRelative": ALPHA_RELATIVE,
            "oldAbsolute": old_absolute,
            "sourceAbsolute": source_absolute,
            "newAbsolute": final_path,
        }
    )


def next_job_folder(jobs_parent: str, folder_name: str) -> str:
    """Pick a free folder. A repeat of the same name and id gets a number."""
    dest = os.path.join(jobs_parent, folder_name)
    if not os.path.lexists(dest):
        return dest
    for number in range(2, 100):
        candidate = os.path.join(jobs_parent, folder_name + " " + str(number))
        if not os.path.lexists(candidate):
            print("That folder already exists. Using " + os.path.basename(candidate), flush=True)
            return candidate
    fail("Too many folders already use the name " + folder_name)


def run(args: argparse.Namespace) -> None:
    name = clean_text(args.name, "Name")
    card_id = clean_text(args.id, "Id")
    project_name = args.project.replace("\\", "/").strip()
    while project_name.startswith("./"):
        project_name = project_name[2:]
    if not project_name or project_name.startswith("/") or any(part in ("", ".", "..") for part in project_name.split("/")):
        fail("Project file name must be a file name or a relative path inside the template folder.")

    clip = clip_file(args.clip)

    template = real_dir(args.template, "Template folder")
    template_data = os.path.join(template, DATA_RELATIVE)
    template_project = os.path.normpath(os.path.join(template, project_name))
    if not os.path.isfile(template_data):
        fail("Data file not found: " + template_data)
    if not os.path.isfile(template_project):
        fail("Project file not found: " + template_project)
    if shutil.which("ditto") is None:
        fail("ditto is not available. This workflow runs on macOS.")

    jobs_parent = ensure_jobs(args.jobs)
    folder_name = "SS-" + folder_part(card_id, "Id") + "|" + folder_part(name, "Name")
    dest = next_job_folder(jobs_parent, folder_name)
    if is_inside(dest, template) or is_inside(template, dest) or dest == template:
        fail("Destination must be outside the template folder.")

    alpha_path, owns_alpha = key_clip(clip)
    copied = False
    try:
        subprocess.run(["ditto", template, dest], check=True)
        copied = True
        data_path = os.path.join(dest, DATA_RELATIVE)
        edit_data(data_path, name, card_id)
        alpha_dest = place_alpha(dest, alpha_path, owns_alpha)
        owns_alpha = False
        project, footage = collect_files(template, dest, project_name)
        point_alpha_at(footage, template, dest, alpha_dest)
        report = {
            "name": name,
            "id": card_id,
            "destination": dest,
            "dataFile": data_path,
            "projectPath": project["newAbsolute"],
        }
        kind = os.environ.get("FOIL_PACK_KIND", "").strip()
        if kind in ("pack-face", "pack-face-2"):
            report["kind"] = kind
        with open(os.path.join(dest, "ae-relink-report.json"), "w", encoding="utf-8") as report_file:
            json.dump(report, report_file, indent=2)
            report_file.write("\n")
        jsx_path = write_jsx(dest, project["newAbsolute"], footage, name, card_id, alpha_dest)
    except Exception:
        if owns_alpha and os.path.isfile(alpha_path):
            os.remove(alpha_path)
        if copied or os.path.isdir(dest):
            remove_created(dest, template)
        raise

    opened = subprocess.run(["open", "-a", "Adobe After Effects 2026", alpha_dest], check=False)
    if opened.returncode != 0:
        fail("After Effects could not open the Greenkey alpha file: " + alpha_dest)
    print("Destination: " + dest)
    print("Opened in After Effects: " + alpha_dest)
    print("Alpha file: " + alpha_dest)
    print("Name: " + name)
    print("Id: " + card_id)
    print("Data file: " + data_path)
    print("JSX: " + jsx_path)
    print("AE_JOB " + json.dumps({"destination": dest}, ensure_ascii=True))


def post_progress(line: str) -> None:
    """Send one runtime line to the operator page that is waiting on this run."""
    url = os.environ.get("INFLUENCER_PROGRESS_URL", "").strip()
    token = os.environ.get("INFLUENCER_PROGRESS_TOKEN", "").strip()
    text = line.strip()
    if not url or not text:
        return
    payload = json.dumps({"line": text}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Progress-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
    except Exception:
        return


class _ProgressStream:
    def __init__(self, stream):
        self.stream = stream
        self.pending = ""

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.stream.flush()
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            post_progress(line)
        return len(text)

    def flush(self) -> None:
        if self.pending:
            post_progress(self.pending)
            self.pending = ""
        self.stream.flush()


def install_progress_reports() -> None:
    if not os.environ.get("INFLUENCER_PROGRESS_URL", "").strip():
        return
    sys.stdout = _ProgressStream(sys.stdout)
    sys.stderr = _ProgressStream(sys.stderr)


def main() -> None:
    install_progress_reports()
    try:
        run(parse_args())
    except JobError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print("Copy failed with exit code " + str(error.returncode) + ".", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as error:
        print("Greenkey could not be reached. " + str(error.reason), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
