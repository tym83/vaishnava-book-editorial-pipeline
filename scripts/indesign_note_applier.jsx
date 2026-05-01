#target "InDesign"
// Copyright 2026 The Vaishnava Book Editorial Pipeline Authors
// SPDX-License-Identifier: Apache-2.0


(function () {
    var originalInteraction = app.scriptPreferences.userInteractionLevel;

    function restoreInteraction() {
        try {
            app.scriptPreferences.userInteractionLevel = originalInteraction;
        } catch (e) {}
    }

    function fail(message) {
        restoreInteraction();
        throw new Error(message);
    }

    function getArg(name, fallback) {
        try {
            if (app.scriptArgs.isDefined(name)) {
                return app.scriptArgs.getValue(name);
            }
        } catch (e) {}
        return fallback;
    }

    function normalizeBool(value, fallback) {
        if (value === undefined || value === null || value === "") return fallback;
        var s = String(value).toLowerCase();
        if (s === "true" || s === "1" || s === "yes") return true;
        if (s === "false" || s === "0" || s === "no") return false;
        return fallback;
    }

    function trim(s) {
        return String(s || "").replace(/^\s+|\s+$/g, "");
    }

    function splitCsv(s) {
        var out = [];
        var parts = String(s || "").split(",");
        for (var i = 0; i < parts.length; i++) {
            var part = trim(parts[i]);
            if (part) out.push(part);
        }
        return out;
    }

    function toFile(path) {
        if (!path) return null;
        return File(path);
    }

    function ensureFileExists(file, label) {
        if (!file || !file.exists) {
            fail(label + " not found: " + (file ? file.fsName : "<empty>"));
        }
    }

    function writeText(path, text) {
        var file = File(path);
        file.encoding = "UTF-8";
        if (!file.open("w")) fail("Could not write file: " + path);
        file.write(text);
        file.close();
    }

    function writeJson(path, obj) {
        if (typeof JSON !== "undefined" && JSON.stringify) {
            writeText(path, JSON.stringify(obj, null, 2));
        } else {
            writeText(path, obj.toSource());
        }
    }

    function readJson(path) {
        var file = File(path);
        ensureFileExists(file, "Issues JSON");
        file.encoding = "UTF-8";
        if (!file.open("r")) fail("Could not read issues file: " + path);
        var text = file.read();
        file.close();
        try {
            if (typeof JSON !== "undefined" && JSON.parse) return JSON.parse(text);
        } catch (e) {}
        return eval("(" + text + ")");
    }

    function cleanText(s) {
        return String(s || "").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "");
    }

    function excerpt(s, limit) {
        var text = cleanText(s);
        var n = limit || 180;
        if (text.length <= n) return text;
        return text.substring(0, n - 1).replace(/\s+$/, "") + "…";
    }

    function issueBody(issue) {
        var lines = [];
        lines.push("[" + String(issue.severity || "warning").toUpperCase() + "] " + String(issue.title || ""));
        if (issue.kind) lines.push("Kind: " + issue.kind);
        if (issue.message) {
            lines.push("");
            lines.push(String(issue.message));
        }
        if (issue.suggestion) {
            lines.push("");
            lines.push("Suggested action:");
            lines.push(String(issue.suggestion));
        }
        var context = issue.context || {};
        var ctxKeys = ["excerpt", "source_excerpt", "target_excerpt"];
        var hasContext = false;
        for (var i = 0; i < ctxKeys.length; i++) {
            if (context[ctxKeys[i]]) {
                if (!hasContext) {
                    lines.push("");
                    lines.push("Context:");
                    hasContext = true;
                }
                lines.push("- " + ctxKeys[i] + ": " + cleanText(String(context[ctxKeys[i]])));
            }
        }
        return lines.join("\n");
    }

    function findMainFrame(doc, preferredLabels) {
        var frames = doc.textFrames.everyItem().getElements();
        var i, j;
        for (j = 0; j < preferredLabels.length; j++) {
            var wanted = preferredLabels[j];
            for (i = 0; i < frames.length; i++) {
                try {
                    if (frames[i].label === wanted && frames[i].isValid && !frames[i].locked) return frames[i];
                } catch (e) {}
            }
        }
        try {
            if (doc.pages.length > 0) {
                var firstFrames = doc.pages[0].textFrames.everyItem().getElements();
                for (i = 0; i < firstFrames.length; i++) {
                    try {
                        if (firstFrames[i].isValid && !firstFrames[i].locked) return firstFrames[i];
                    } catch (e) {}
                }
            }
        } catch (e) {}
        return null;
    }

    function firstUnlockedFrameOnPage(page) {
        try {
            var frames = page.textFrames.everyItem().getElements();
            for (var i = 0; i < frames.length; i++) {
                try {
                    if (frames[i].isValid && !frames[i].locked) return frames[i];
                } catch (e) {}
            }
        } catch (e) {}
        return null;
    }

    function storyForIssue(doc, issue, fallbackLabels) {
        var anchor = issue.anchor || {};
        var labels = [];
        if (anchor.story_label) labels.push(String(anchor.story_label));
        for (var i = 0; i < fallbackLabels.length; i++) labels.push(fallbackLabels[i]);
        var frame = findMainFrame(doc, labels);
        return frame ? frame.parentStory : null;
    }

    function paragraphForIssue(doc, issue, fallbackLabels) {
        var anchor = issue.anchor || {};
        if (anchor.part && anchor.part !== "word/document.xml") {
            return { paragraph: null, reason: "unsupported_part:" + anchor.part };
        }
        if (anchor.paragraph_index) {
            var story = storyForIssue(doc, issue, fallbackLabels);
            if (!story) return { paragraph: null, reason: "story_not_found" };
            var idx = parseInt(anchor.paragraph_index, 10);
            if (isNaN(idx) || idx < 1 || idx > story.paragraphs.length) {
                return { paragraph: null, reason: "paragraph_out_of_range:" + anchor.paragraph_index };
            }
            return { paragraph: story.paragraphs[idx - 1], reason: "" };
        }
        if (anchor.page) {
            var pageNum = parseInt(anchor.page, 10);
            if (isNaN(pageNum) || pageNum < 1 || pageNum > doc.pages.length) {
                return { paragraph: null, reason: "page_out_of_range:" + anchor.page };
            }
            var frame = firstUnlockedFrameOnPage(doc.pages[pageNum - 1]);
            if (!frame || !frame.parentStory || frame.parentStory.paragraphs.length < 1) {
                return { paragraph: null, reason: "page_frame_not_found:" + anchor.page };
            }
            return { paragraph: frame.parentStory.paragraphs[0], reason: "" };
        }
        var fallbackStory = storyForIssue(doc, issue, fallbackLabels);
        if (!fallbackStory || fallbackStory.paragraphs.length < 1) {
            return { paragraph: null, reason: "default_story_not_found" };
        }
        return { paragraph: fallbackStory.paragraphs[0], reason: "" };
    }

    function setNoteText(note, text) {
        try {
            note.texts[0].contents = text;
            return true;
        } catch (e1) {}
        try {
            note.contents = text;
            return true;
        } catch (e2) {}
        return false;
    }

    function tryCreateNote(paragraph, text) {
        var ip = null;
        try { ip = paragraph.insertionPoints[0]; } catch (e) {}
        if (!ip) return { ok: false, mode: "", error: "no_insertion_point" };

        try {
            var note1 = ip.notes.add();
            if (setNoteText(note1, text)) return { ok: true, mode: "ip.notes.add" };
        } catch (e1) {}

        try {
            var note2 = paragraph.notes.add();
            if (setNoteText(note2, text)) return { ok: true, mode: "paragraph.notes.add" };
        } catch (e2) {}

        try {
            var note3 = ip.parentStory.notes.add(ip);
            if (setNoteText(note3, text)) return { ok: true, mode: "story.notes.add(ip)" };
        } catch (e3) {}

        try {
            var note4 = ip.parentStory.notes.add(LocationOptions.AFTER, ip);
            if (setNoteText(note4, text)) return { ok: true, mode: "story.notes.add(after,ip)" };
        } catch (e4) {}

        return { ok: false, mode: "", error: "note_api_failed" };
    }

    function appendLabel(target, key, text) {
        var existing = "";
        try { existing = target.extractLabel(key); } catch (e) {}
        var merged = existing ? existing + "\n\n---\n\n" + text : text;
        try {
            target.insertLabel(key, merged);
            return true;
        } catch (e2) {
            return false;
        }
    }

    function reportText(data) {
        var lines = [];
        lines.push("InDesign Review Note Apply Report");
        lines.push("");
        lines.push("Document: " + data.document);
        lines.push("Issues file: " + data.issuesFile);
        lines.push("Saved: " + data.saved);
        lines.push("");
        lines.push("Summary:");
        lines.push("- applied as notes: " + data.appliedNotes.length);
        lines.push("- applied as labels: " + data.appliedLabels.length);
        lines.push("- skipped: " + data.skipped.length);
        lines.push("");
        lines.push("Applied as notes:");
        if (data.appliedNotes.length === 0) {
            lines.push("- none");
        } else {
            for (var i = 0; i < Math.min(data.appliedNotes.length, 200); i++) {
                var item = data.appliedNotes[i];
                lines.push("- " + item.id + " page=" + item.page + " paragraph=" + item.paragraphIndex + " mode=" + item.mode);
            }
        }
        lines.push("");
        lines.push("Applied as labels:");
        if (data.appliedLabels.length === 0) {
            lines.push("- none");
        } else {
            for (var j = 0; j < Math.min(data.appliedLabels.length, 200); j++) {
                var item2 = data.appliedLabels[j];
                lines.push("- " + item2.id + " page=" + item2.page + " paragraph=" + item2.paragraphIndex + " key=" + item2.labelKey);
            }
        }
        lines.push("");
        lines.push("Skipped:");
        if (data.skipped.length === 0) {
            lines.push("- none");
        } else {
            for (var k = 0; k < Math.min(data.skipped.length, 200); k++) {
                var item3 = data.skipped[k];
                lines.push("- " + item3.id + " reason=" + item3.reason);
            }
        }
        lines.push("");
        lines.push("Note:");
        lines.push("- If `applied as labels` is non-zero, your InDesign version or note API path needs a small runtime adjustment.");
        return lines.join("\n");
    }

    try {
        var inputArg = getArg("input", "");
        var issuesArg = getArg("issues", "");
        var reportArg = getArg("report", "");
        var reportJsonArg = getArg("report_json", "");
        var saveAfter = normalizeBool(getArg("save_after", "false"), false);
        var labelsArg = getArg("labels", "main_story,main-story,main_text,mainText");

        app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;

        var doc;
        if (inputArg) {
            var inputFile = toFile(inputArg);
            ensureFileExists(inputFile, "Input INDD");
            doc = app.open(inputFile, false);
        } else if (app.documents.length > 0) {
            doc = app.activeDocument;
        } else {
            fail("No active document and no input path provided.");
        }

        if (!issuesArg) fail("issues argument is required");
        var issueBundle = readJson(issuesArg);
        var fallbackLabels = splitCsv(labelsArg);

        var appliedNotes = [];
        var appliedLabels = [];
        var skipped = [];

        var issues = issueBundle.issues || [];
        for (var i = 0; i < issues.length; i++) {
            var issue = issues[i];
            var resolved = paragraphForIssue(doc, issue, fallbackLabels);
            if (!resolved.paragraph) {
                skipped.push({ id: issue.id || ("issue-" + (i + 1)), reason: resolved.reason });
                continue;
            }

            var paragraph = resolved.paragraph;
            var page = "";
            try {
                if (paragraph.lines.length > 0 && paragraph.lines[0].parentTextFrames.length > 0 && paragraph.lines[0].parentTextFrames[0].parentPage) {
                    page = paragraph.lines[0].parentTextFrames[0].parentPage.name;
                }
            } catch (e) {}
            var paragraphIndex = "";
            try {
                paragraphIndex = paragraph.index + 1;
            } catch (e2) {
                paragraphIndex = issue.anchor && issue.anchor.paragraph_index ? issue.anchor.paragraph_index : "";
            }

            var content = issueBody(issue);
            var result = tryCreateNote(paragraph, content);
            if (result.ok) {
                appliedNotes.push({
                    id: issue.id || ("issue-" + (i + 1)),
                    page: page,
                    paragraphIndex: paragraphIndex,
                    mode: result.mode
                });
                continue;
            }

            var labelKey = "codex_review_" + String(issue.id || ("issue_" + (i + 1)));
            if (appendLabel(paragraph, labelKey, content)) {
                appliedLabels.push({
                    id: issue.id || ("issue-" + (i + 1)),
                    page: page,
                    paragraphIndex: paragraphIndex,
                    labelKey: labelKey
                });
            } else {
                skipped.push({
                    id: issue.id || ("issue-" + (i + 1)),
                    reason: result.error || "label_fallback_failed"
                });
            }
        }

        var summary = {
            document: doc.fullName ? doc.fullName.fsName : doc.name,
            issuesFile: issuesArg,
            saved: false,
            appliedNotes: appliedNotes,
            appliedLabels: appliedLabels,
            skipped: skipped
        };

        if (saveAfter) {
            try {
                doc.save();
                summary.saved = true;
            } catch (saveErr) {}
        }

        var reportPath = reportArg;
        if (!reportPath) {
            try {
                reportPath = doc.fullName.fsName.replace(/\.indd$/i, "") + ".review-notes-report.md";
            } catch (e3) {
                reportPath = Folder.desktop.fsName + "/review-notes-report.md";
            }
        }
        writeText(reportPath, reportText(summary));

        var jsonPath = reportJsonArg;
        if (!jsonPath) {
            jsonPath = reportPath.replace(/\.md$/i, ".json");
        }
        writeJson(jsonPath, summary);

        restoreInteraction();
    } catch (e) {
        restoreInteraction();
        throw e;
    }
})();
