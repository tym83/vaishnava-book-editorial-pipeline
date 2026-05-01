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
        if (value === undefined || value === null || value === "") {
            return fallback;
        }
        var s = String(value).toLowerCase();
        if (s === "true" || s === "1" || s === "yes") return true;
        if (s === "false" || s === "0" || s === "no") return false;
        return fallback;
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

    function trim(s) {
        return String(s).replace(/^\s+|\s+$/g, "");
    }

    function splitCsv(s) {
        var out = [];
        var parts = String(s).split(",");
        for (var i = 0; i < parts.length; i++) {
            var part = trim(parts[i]);
            if (part) out.push(part);
        }
        return out;
    }

    function collectStyleNames(styleArray) {
        var out = {};
        for (var i = 0; i < styleArray.length; i++) {
            try {
                var st = styleArray[i];
                var name = st.name;
                if (name && name.charAt(0) !== "[") {
                    out[name] = true;
                }
            } catch (e) {}
        }
        return out;
    }

    function diffKeys(beforeMap, afterMap) {
        var out = [];
        for (var key in afterMap) {
            if (afterMap.hasOwnProperty(key) && !beforeMap[key]) {
                out.push(key);
            }
        }
        out.sort();
        return out;
    }

    function configureImportPrefs() {
        var prefs = app.wordRTFImportPreferences;
        try { prefs.removeFormatting = false; } catch (e) {}
        try { prefs.preserveGraphics = false; } catch (e) {}
        try { prefs.importEndnotes = true; } catch (e) {}
        try { prefs.importFootnotes = true; } catch (e) {}
        try { prefs.preserveTrackChanges = false; } catch (e) {}
        try { prefs.convertBulletsAndNumbersToText = false; } catch (e) {}
        try { prefs.useTypographersQuotes = true; } catch (e) {}
    }

    function configureSmartReflow(doc) {
        try { doc.textPreferences.smartTextReflow = true; } catch (e) {}
        try { doc.textPreferences.addPages = AddPageOptions.END_OF_STORY; } catch (e) {}
        try { doc.textPreferences.limitToMasterTextFrames = false; } catch (e) {}
        try { doc.textPreferences.removeEmptyPages = false; } catch (e) {}
        try { doc.textPreferences.preserveFacingPageSpreads = true; } catch (e) {}
    }

    function findMainFrame(doc, preferredLabels) {
        var frames = doc.textFrames.everyItem().getElements();
        var i, j;

        for (j = 0; j < preferredLabels.length; j++) {
            var wanted = preferredLabels[j];
            for (i = 0; i < frames.length; i++) {
                try {
                    if (frames[i].label === wanted && frames[i].isValid && !frames[i].locked) {
                        return frames[i];
                    }
                } catch (e) {}
            }
        }

        try {
            if (doc.pages.length > 0) {
                var pageFrames = doc.pages[0].textFrames.everyItem().getElements();
                for (i = 0; i < pageFrames.length; i++) {
                    try {
                        if (pageFrames[i].isValid && !pageFrames[i].locked) {
                            return pageFrames[i];
                        }
                    } catch (e) {}
                }
            }
        } catch (e) {}

        for (i = 0; i < frames.length; i++) {
            try {
                if (frames[i].isValid && !frames[i].locked) {
                    return frames[i];
                }
            } catch (e) {}
        }
        return null;
    }

    function clearStory(story) {
        try {
            story.contents = "";
        } catch (e) {
            fail("Could not clear target story: " + e);
        }
    }

    function writeReport(path, report) {
        var file = File(path);
        file.encoding = "UTF-8";
        if (!file.open("w")) {
            fail("Could not write report: " + path);
        }
        file.write(report);
        file.close();
    }

    function reportText(data) {
        var lines = [];
        lines.push("Word -> InDesign Import Report");
        lines.push("");
        lines.push("Template: " + data.template);
        lines.push("Input DOCX: " + data.input);
        lines.push("Output INDD: " + data.output);
        lines.push("Target frame label: " + data.targetFrameLabel);
        lines.push("Target page: " + data.targetPage);
        lines.push("Pages before import: " + data.pagesBefore);
        lines.push("Pages after import: " + data.pagesAfter);
        lines.push("Pages added: " + data.pagesAdded);
        lines.push("Story overset: " + data.storyOverflows);
        lines.push("");
        lines.push("New paragraph styles after import:");
        if (data.newParagraphStyles.length === 0) {
            lines.push("- none");
        } else {
            for (var i = 0; i < data.newParagraphStyles.length; i++) {
                lines.push("- " + data.newParagraphStyles[i]);
            }
        }
        lines.push("");
        lines.push("New character styles after import:");
        if (data.newCharacterStyles.length === 0) {
            lines.push("- none");
        } else {
            for (var j = 0; j < data.newCharacterStyles.length; j++) {
                lines.push("- " + data.newCharacterStyles[j]);
            }
        }
        lines.push("");
        lines.push("Notes:");
        lines.push("- Script expects Word and InDesign styles to have identical names.");
        lines.push("- If new styles appeared, review style mapping manually.");
        lines.push("- If story overset is true, inspect layout and frame chain.");
        return lines.join("\n");
    }

    try {
        var templateArg = getArg("template", "");
        var inputArg = getArg("input", "");
        var outputArg = getArg("output", "");
        var reportArg = getArg("report", "");
        var labelsArg = getArg("labels", "main_story,main-story,main_text,mainText");
        var clearExisting = normalizeBool(getArg("clear_existing", "true"), true);
        var showImportOptions = normalizeBool(getArg("show_import_options", "false"), false);

        if (!showImportOptions) {
            app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
        }

        var templateFile = toFile(templateArg);
        var inputFile = toFile(inputArg);
        var outputFile = toFile(outputArg);

        if (!templateFile) templateFile = File.openDialog("Select InDesign template (.indd)");
        if (!inputFile) inputFile = File.openDialog("Select Word file (.docx/.doc)");
        if (!outputFile) outputFile = File.saveDialog("Save output InDesign file as");

        ensureFileExists(templateFile, "Template");
        ensureFileExists(inputFile, "Input DOCX");
        if (!outputFile) fail("Output path not provided.");

        configureImportPrefs();

        var doc = app.open(templateFile, false);
        configureSmartReflow(doc);

        var pageCountBefore = doc.pages.length;
        var paraBefore = collectStyleNames(doc.allParagraphStyles);
        var charBefore = collectStyleNames(doc.allCharacterStyles);

        var labels = splitCsv(labelsArg);
        var mainFrame = findMainFrame(doc, labels);
        if (!mainFrame) {
            fail("No target text frame found. Label a frame as main_story/main-story/main_text or ensure the first page has a text frame.");
        }

        var story = mainFrame.parentStory;
        if (clearExisting) {
            clearStory(story);
        }

        var insertion = story.insertionPoints[0];
        insertion.place(inputFile, showImportOptions);
        story.recompose();

        var pageCountAfter = doc.pages.length;
        var paraAfter = collectStyleNames(doc.allParagraphStyles);
        var charAfter = collectStyleNames(doc.allCharacterStyles);

        doc.save(outputFile);

        var reportData = {
            template: templateFile.fsName,
            input: inputFile.fsName,
            output: outputFile.fsName,
            targetFrameLabel: mainFrame.label || "",
            targetPage: mainFrame.parentPage ? mainFrame.parentPage.name : "",
            pagesBefore: pageCountBefore,
            pagesAfter: pageCountAfter,
            pagesAdded: pageCountAfter - pageCountBefore,
            storyOverflows: story.overflows,
            newParagraphStyles: diffKeys(paraBefore, paraAfter),
            newCharacterStyles: diffKeys(charBefore, charAfter)
        };

        if (reportArg) {
            writeReport(reportArg, reportText(reportData));
        } else {
            var autoReport = outputFile.fsName.replace(/\.indd$/i, "") + ".import-report.txt";
            writeReport(autoReport, reportText(reportData));
        }

        doc.save();
        restoreInteraction();
    } catch (e) {
        restoreInteraction();
        throw e;
    }
})();
