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

    function trim(s) {
        return String(s).replace(/^\s+|\s+$/g, "");
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

    function toFile(path) {
        if (!path) return null;
        return File(path);
    }

    function ensureFileExists(file, label) {
        if (!file || !file.exists) {
            fail(label + " not found: " + (file ? file.fsName : "<empty>"));
        }
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

    function writeReport(path, report) {
        var file = File(path);
        file.encoding = "UTF-8";
        if (!file.open("w")) {
            fail("Could not write report: " + path);
        }
        file.write(report);
        file.close();
    }

    function writeJson(path, obj) {
        if (typeof JSON !== "undefined" && JSON.stringify) {
            writeReport(path, JSON.stringify(obj, null, 2));
        } else {
            writeReport(path, obj.toSource());
        }
    }

    function pageNameForLine(line) {
        try {
            if (line.parentTextFrames.length > 0 && line.parentTextFrames[0].parentPage) {
                return line.parentTextFrames[0].parentPage.name;
            }
        } catch (e) {}
        return "";
    }

    function framePageName(frame) {
        try {
            if (frame.parentPage) return frame.parentPage.name;
        } catch (e) {}
        return "";
    }

    function pushLimited(array, item, limit) {
        if (array.length < limit) {
            array.push(item);
        }
    }

    function collectFontIssues(doc) {
        var out = [];
        var seen = {};
        try {
            var fonts = doc.fonts.everyItem().getElements();
            for (var i = 0; i < fonts.length; i++) {
                try {
                    var font = fonts[i];
                    var key = font.fullName || font.name;
                    if (seen[key]) continue;
                    seen[key] = true;
                    var status = String(font.status);
                    if (status !== String(FontStatus.INSTALLED)) {
                        out.push({
                            name: key,
                            status: status
                        });
                    }
                } catch (e) {}
            }
        } catch (e) {}
        return out;
    }

    function styleName(obj) {
        try {
            return obj.name || "";
        } catch (e) {
            return "";
        }
    }

    function findOrCreateLanguage(doc, preferredNames) {
        for (var i = 0; i < preferredNames.length; i++) {
            try {
                var lang = doc.languagesWithVendors.itemByName(preferredNames[i]);
                if (lang && lang.isValid) return lang;
            } catch (e) {}
            try {
                var lang2 = app.languagesWithVendors.itemByName(preferredNames[i]);
                if (lang2 && lang2.isValid) return lang2;
            } catch (e) {}
        }
        return null;
    }

    function grepReplace(doc, findWhat, changeTo) {
        app.findGrepPreferences = NothingEnum.NOTHING;
        app.changeGrepPreferences = NothingEnum.NOTHING;
        app.findChangeGrepOptions.includeFootnotes = true;
        app.findChangeGrepOptions.includeHiddenLayers = false;
        app.findChangeGrepOptions.includeLockedLayersForFind = false;
        app.findChangeGrepOptions.includeLockedStoriesForFind = false;
        app.findChangeGrepOptions.includeMasterPages = false;
        app.findGrepPreferences.findWhat = findWhat;
        app.changeGrepPreferences.changeTo = changeTo;
        var changed = doc.changeGrep();
        app.findGrepPreferences = NothingEnum.NOTHING;
        app.changeGrepPreferences = NothingEnum.NOTHING;
        return changed ? changed.length : 0;
    }

    function applySafeFixes(doc, bodyStyleNames, noHyphenStyleNames) {
        var stats = {
            nbspOneLetter: 0,
            nbspPercent: 0,
            nbspNumero: 0,
            nbspReferences: 0,
            nbspDashLeft: 0,
            hyphenationBodyTouched: [],
            hyphenationDisabledTouched: []
        };

        // Only safe Russian one-letter prepositions/conjunctions.
        stats.nbspOneLetter += grepReplace(
            doc,
            "(^|[\\s\\(\\[«„\"'])(([ВвКкСсУуИиОоАаЯя]))\\x20+([A-Za-zА-Яа-яЁё0-9])",
            "$1$2~S$4"
        );
        stats.nbspPercent += grepReplace(doc, "(\\d)\\x20+(%)", "$1~S$2");
        stats.nbspNumero += grepReplace(doc, "(№)\\x20+(\\d)", "$1~S$2");
        stats.nbspReferences += grepReplace(
            doc,
            "((?:[Рр]ис\\.|[Тт]абл\\.|[Гг]л\\.|[Сс]тр\\.|[Пп]рим\\.|[Тт]\\.))\\x20+(\\d)",
            "$1~S$2"
        );
        // Keep running-text dash with the previous token so the line does not start with a dash after reflow.
        stats.nbspDashLeft += grepReplace(
            doc,
            "([A-Za-zА-Яа-яЁё0-9»”\\)\\]])\\x20+([—–])\\x20+([A-Za-zА-Яа-яЁё0-9«„\"\\(\\[])",
            "$1~S$2 $3"
        );

        for (var i = 0; i < bodyStyleNames.length; i++) {
            try {
                var style = doc.paragraphStyles.itemByName(bodyStyleNames[i]);
                if (style && style.isValid) {
                    if (style.hyphenation !== true) {
                        style.hyphenation = true;
                        stats.hyphenationBodyTouched.push(bodyStyleNames[i]);
                    }
                }
            } catch (e) {}
        }

        for (var j = 0; j < noHyphenStyleNames.length; j++) {
            try {
                var style2 = doc.paragraphStyles.itemByName(noHyphenStyleNames[j]);
                if (style2 && style2.isValid) {
                    if (style2.hyphenation !== false) {
                        style2.hyphenation = false;
                        stats.hyphenationDisabledTouched.push(noHyphenStyleNames[j]);
                    }
                }
            } catch (e) {}
        }
        return stats;
    }

    function collectOversetFrames(doc) {
        var out = [];
        try {
            var frames = doc.textFrames.everyItem().getElements();
            for (var i = 0; i < frames.length; i++) {
                var frame = frames[i];
                try {
                    if (frame.overflows) {
                        out.push({
                            page: framePageName(frame),
                            label: frame.label || "",
                            storyId: frame.parentStory ? frame.parentStory.id : ""
                        });
                    }
                } catch (e) {}
            }
        } catch (e) {}
        return out;
    }

    function collectLegacyIssues(doc) {
        var out = [];
        try {
            var stories = doc.stories.everyItem().getElements();
            var re = /[\uE000-\uF8FF]/;
            for (var i = 0; i < stories.length; i++) {
                var story = stories[i];
                var ranges = story.textStyleRanges.everyItem().getElements();
                for (var j = 0; j < ranges.length; j++) {
                    var range = ranges[j];
                    var text = "";
                    try { text = range.contents; } catch (e) {}
                    var fontName = "";
                    try { fontName = String(range.appliedFont.fullName || range.appliedFont.name || ""); } catch (e) {}
                    var hasPua = text && re.test(text);
                    var hasLegacyFont = /gaura/i.test(fontName);
                    if (hasPua || hasLegacyFont) {
                        pushLimited(out, {
                            page: pageNameForLine(range.lines[0]),
                            style: styleName(range.appliedParagraphStyle),
                            font: fontName,
                            problem: hasPua ? "private_use_unicode" : "legacy_font",
                            excerpt: excerpt(text, 140)
                        }, 400);
                    }
                }
            }
        } catch (e) {}
        return out;
    }

    function collectLanguageIssues(doc, russianLanguage) {
        var out = [];
        if (!russianLanguage) return out;
        try {
            var stories = doc.stories.everyItem().getElements();
            var cyrillic = /[А-Яа-яЁё]/;
            for (var i = 0; i < stories.length; i++) {
                var story = stories[i];
                var ranges = story.textStyleRanges.everyItem().getElements();
                for (var j = 0; j < ranges.length; j++) {
                    var range = ranges[j];
                    var text = "";
                    try { text = range.contents; } catch (e) {}
                    if (!text || !cyrillic.test(text)) continue;
                    try {
                        var lang = range.appliedLanguage;
                        if (!lang || !lang.isValid || lang.name !== russianLanguage.name) {
                            pushLimited(out, {
                                language: lang && lang.isValid ? lang.name : "",
                                style: styleName(range.appliedParagraphStyle),
                                excerpt: excerpt(text, 140)
                            }, 400);
                        }
                    } catch (e) {}
                }
            }
        } catch (e) {}
        return out;
    }

    function collectOverrideIssues(doc) {
        var out = {
            paragraph: [],
            character: []
        };
        try {
            var stories = doc.stories.everyItem().getElements();
            for (var i = 0; i < stories.length; i++) {
                var story = stories[i];
                var paras = story.paragraphs.everyItem().getElements();
                for (var j = 0; j < paras.length; j++) {
                    var p = paras[j];
                    var txt = "";
                    try { txt = p.contents; } catch (e) {}
                    try {
                        if (p.texts[0].textHasOverrides(StyleType.PARAGRAPH_STYLE_TYPE, true)) {
                            pushLimited(out.paragraph, {
                                page: pageNameForLine(p.lines[0]),
                                style: styleName(p.appliedParagraphStyle),
                                excerpt: excerpt(txt, 140)
                            }, 400);
                        }
                    } catch (e) {}
                    try {
                        if (p.texts[0].textHasOverrides(StyleType.CHARACTER_STYLE_TYPE, true)) {
                            pushLimited(out.character, {
                                page: pageNameForLine(p.lines[0]),
                                style: styleName(p.appliedParagraphStyle),
                                excerpt: excerpt(txt, 140)
                            }, 400);
                        }
                    } catch (e) {}
                }
            }
        } catch (e) {}
        return out;
    }

    function collectFootnoteIssues(doc) {
        var out = [];
        try {
            var stories = doc.stories.everyItem().getElements();
            for (var i = 0; i < stories.length; i++) {
                var story = stories[i];
                var footnotes = story.footnotes.everyItem().getElements();
                for (var j = 0; j < footnotes.length; j++) {
                    try {
                        var note = footnotes[j];
                        var paragraphs = note.paragraphs.everyItem().getElements();
                        for (var k = 0; k < paragraphs.length; k++) {
                            var p = paragraphs[k];
                            if (p.hyphenation === false) {
                                pushLimited(out, {
                                    page: pageNameForLine(p.lines[0]),
                                    style: styleName(p.appliedParagraphStyle),
                                    problem: "hyphenation_off",
                                    excerpt: excerpt(p.contents, 140)
                                }, 400);
                            }
                        }
                    } catch (e) {}
                }
            }
        } catch (e) {}
        return out;
    }

    function collectDanglingDashIssues(doc) {
        var out = [];
        try {
            var stories = doc.stories.everyItem().getElements();
            for (var i = 0; i < stories.length; i++) {
                var paras = stories[i].paragraphs.everyItem().getElements();
                for (var j = 0; j < paras.length; j++) {
                    var p = paras[j];
                    var lines;
                    try {
                        lines = p.lines;
                    } catch (e) {
                        continue;
                    }
                    if (!lines || lines.length < 2) continue;
                    for (var k = 1; k < lines.length; k++) {
                        var lineText = "";
                        try { lineText = cleanText(lines[k].contents); } catch (e) {}
                        if (/^[—–]/.test(lineText)) {
                            pushLimited(out, {
                                page: pageNameForLine(lines[k]),
                                style: styleName(p.appliedParagraphStyle),
                                kind: "line_starts_with_dash",
                                excerpt: excerpt(p.contents, 140),
                                line: excerpt(lineText, 80)
                            }, 400);
                        }
                    }
                }
            }
        } catch (e) {}
        return out;
    }

    function collectWidowOrphanIssues(doc) {
        var out = [];
        try {
            var stories = doc.stories.everyItem().getElements();
            for (var i = 0; i < stories.length; i++) {
                var story = stories[i];
                var paras = story.paragraphs.everyItem().getElements();
                for (var j = 0; j < paras.length; j++) {
                    var p = paras[j];
                    var lines;
                    try {
                        lines = p.lines;
                    } catch (e) {
                        continue;
                    }
                    if (!lines || lines.length < 2) continue;

                    var counts = {};
                    var pageOrder = [];
                    for (var k = 0; k < lines.length; k++) {
                        var page = pageNameForLine(lines[k]) || "<unknown>";
                        if (!counts[page]) {
                            counts[page] = 0;
                            pageOrder.push(page);
                        }
                        counts[page] += 1;
                    }
                    if (pageOrder.length < 2) continue;

                    var firstPage = pageOrder[0];
                    var lastPage = pageOrder[pageOrder.length - 1];
                    if (counts[firstPage] === 1) {
                        pushLimited(out, {
                            page: firstPage,
                            style: styleName(p.appliedParagraphStyle),
                            kind: "orphan_first_line",
                            excerpt: excerpt(p.contents, 140)
                        }, 400);
                    }
                    if (counts[lastPage] === 1) {
                        pushLimited(out, {
                            page: lastPage,
                            style: styleName(p.appliedParagraphStyle),
                            kind: "widow_last_line",
                            excerpt: excerpt(p.contents, 140)
                        }, 400);
                    }
                }
            }
        } catch (e) {}
        return out;
    }

    function collectHyphenationStyleIssues(doc, bodyStyleNames, noHyphenStyleNames) {
        var out = [];
        for (var i = 0; i < bodyStyleNames.length; i++) {
            try {
                var bodyStyle = doc.paragraphStyles.itemByName(bodyStyleNames[i]);
                if (bodyStyle && bodyStyle.isValid && bodyStyle.hyphenation !== true) {
                    pushLimited(out, {
                        style: bodyStyleNames[i],
                        expected: "true",
                        actual: String(bodyStyle.hyphenation)
                    }, 120);
                }
            } catch (e) {}
        }
        for (var j = 0; j < noHyphenStyleNames.length; j++) {
            try {
                var noStyle = doc.paragraphStyles.itemByName(noHyphenStyleNames[j]);
                if (noStyle && noStyle.isValid && noStyle.hyphenation !== false) {
                    pushLimited(out, {
                        style: noHyphenStyleNames[j],
                        expected: "false",
                        actual: String(noStyle.hyphenation)
                    }, 120);
                }
            } catch (e) {}
        }
        return out;
    }

    function collectFrontMatterFlags(doc) {
        var out = [];
        try {
            var stories = doc.stories.everyItem().getElements();
            var firstH1 = null;
            var bodyBeforeH1 = 0;
            for (var i = 0; i < stories.length; i++) {
                var paras = stories[i].paragraphs.everyItem().getElements();
                for (var j = 0; j < paras.length; j++) {
                    var p = paras[j];
                    var style = styleName(p.appliedParagraphStyle);
                    if (style === "Заголовок 1") {
                        if (!firstH1) {
                            firstH1 = {
                                page: pageNameForLine(p.lines[0]),
                                excerpt: excerpt(p.contents, 120)
                            };
                        }
                        break;
                    }
                    if (style === "Основной текст") {
                        bodyBeforeH1 += 1;
                    }
                }
                if (firstH1) break;
            }

            if (!firstH1) {
                out.push({
                    kind: "missing_h1",
                    detail: "Не найден первый заголовок главы со стилем `Заголовок 1`."
                });
                return out;
            }

            var pageNum = parseInt(firstH1.page, 10);
            if (!isNaN(pageNum) && pageNum > 5) {
                out.push({
                    kind: "late_first_h1",
                    detail: "Первый `Заголовок 1` начинается только на странице " + firstH1.page + "."
                });
            }
            if (bodyBeforeH1 > 12) {
                out.push({
                    kind: "body_before_first_h1",
                    detail: "До первого `Заголовок 1` найдено " + bodyBeforeH1 + " абзацев `Основной текст`."
                });
            }
        } catch (e) {}
        return out;
    }

    function reportText(data) {
        function pushSection(lines, title, items, renderFn, limit) {
            lines.push(title);
            if (!items || items.length === 0) {
                lines.push("- none");
                lines.push("");
                return;
            }
            lines.push("- count: " + items.length);
            var max = Math.min(items.length, limit || 60);
            for (var i = 0; i < max; i++) {
                lines.push("- " + renderFn(items[i]));
            }
            if (items.length > max) {
                lines.push("- ... " + (items.length - max) + " more omitted");
            }
            lines.push("");
        }

        var lines = [];
        lines.push("InDesign Layout QA Report");
        lines.push("");
        lines.push("Document: " + data.document);
        lines.push("Safe fixes applied: " + data.applySafeFixes);
        lines.push("Document saved: " + data.saved);
        lines.push("");
        lines.push("Fixes:");
        lines.push("- one-letter nbsp replacements: " + data.fixStats.nbspOneLetter);
        lines.push("- percent nbsp replacements: " + data.fixStats.nbspPercent);
        lines.push("- numero nbsp replacements: " + data.fixStats.nbspNumero);
        lines.push("- reference nbsp replacements: " + data.fixStats.nbspReferences);
        lines.push("- dash-left nbsp replacements: " + data.fixStats.nbspDashLeft);
        lines.push("- hyphenation enabled on styles: " + data.fixStats.hyphenationBodyTouched.join(", "));
        lines.push("- hyphenation disabled on styles: " + data.fixStats.hyphenationDisabledTouched.join(", "));
        lines.push("");
        pushSection(lines, "Overset Frames", data.oversetFrames, function (x) {
            return "page=" + x.page + " label=" + x.label + " story=" + x.storyId;
        }, 40);
        pushSection(lines, "Missing Fonts", data.fontIssues, function (x) {
            return x.name + " [" + x.status + "]";
        }, 40);
        pushSection(lines, "Hyphenation Style Issues", data.hyphenationStyleIssues, function (x) {
            return "style=" + x.style + " expected=" + x.expected + " actual=" + x.actual;
        }, 60);
        pushSection(lines, "Paragraph Overrides", data.overrideIssues.paragraph, function (x) {
            return "page=" + x.page + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Character Overrides", data.overrideIssues.character, function (x) {
            return "page=" + x.page + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Language Issues", data.languageIssues, function (x) {
            return "lang=" + x.language + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Legacy Symbol Issues", data.legacyIssues, function (x) {
            return "page=" + x.page + " problem=" + x.problem + " font=" + x.font + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Footnote Issues", data.footnoteIssues, function (x) {
            return "page=" + x.page + " problem=" + x.problem + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Dangling Dash Suspects", data.danglingDashIssues, function (x) {
            return "page=" + x.page + " kind=" + x.kind + " style=" + x.style + " line=" + x.line + " paragraph=" + x.excerpt;
        }, 60);
        pushSection(lines, "Widow/Orphan Suspects", data.widowOrphanIssues, function (x) {
            return "page=" + x.page + " kind=" + x.kind + " style=" + x.style + " text=" + x.excerpt;
        }, 60);
        pushSection(lines, "Front Matter Flags", data.frontMatterFlags, function (x) {
            return "kind=" + x.kind + " detail=" + x.detail;
        }, 20);
        lines.push("Notes:");
        lines.push("- `Widow/Orphan Suspects` are heuristics only and need visual confirmation.");
        lines.push("- `Language Issues` are checked only for Cyrillic text ranges.");
        lines.push("- `Paragraph Overrides` and `Character Overrides` depend on InDesign override detection and should be spot-checked.");
        return lines.join("\n");
    }

    try {
        var inputArg = getArg("input", "");
        var reportArg = getArg("report", "");
        var reportJsonArg = getArg("report_json", "");
        var saveAfter = normalizeBool(getArg("save_after", "false"), false);
        var applySafeFixesFlag = normalizeBool(getArg("apply_safe_fixes", "true"), true);
        var russianArg = getArg("russian_language_names", "Russian: Russian,Russian");
        var bodyStylesArg = getArg(
            "body_styles",
            "Основной текст,Цитата 1,Цитата 2,Письмо,Источник,Сноска 1,Сноска 2,Сноска 3,Сноска 4,Список нумерованный 1,Список нумерованный 2,Список ненумерованный 1,Список ненумерованный 2,Перевод шлоки"
        );
        var noHyphenArg = getArg(
            "no_hyphen_styles",
            "Заголовок 1,Заголовок 2,Заголовок 3,Заголовок 4,Источник,Подпись к иллюстрации"
        );

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

        var russianLanguage = findOrCreateLanguage(doc, splitCsv(russianArg));
        var bodyStyleNames = splitCsv(bodyStylesArg);
        var noHyphenStyleNames = splitCsv(noHyphenArg);

        var fixStats = {
            nbspOneLetter: 0,
            nbspPercent: 0,
            nbspNumero: 0,
            nbspReferences: 0,
            nbspDashLeft: 0,
            hyphenationBodyTouched: [],
            hyphenationDisabledTouched: []
        };
        if (applySafeFixesFlag) {
            fixStats = applySafeFixes(doc, bodyStyleNames, noHyphenStyleNames);
            try { doc.recompose(); } catch (e) {}
        }

        var result = {
            document: doc.fullName ? doc.fullName.fsName : doc.name,
            applySafeFixes: applySafeFixesFlag,
            saved: false,
            fixStats: fixStats,
            oversetFrames: collectOversetFrames(doc),
            fontIssues: collectFontIssues(doc),
            hyphenationStyleIssues: collectHyphenationStyleIssues(doc, bodyStyleNames, noHyphenStyleNames),
            overrideIssues: collectOverrideIssues(doc),
            languageIssues: collectLanguageIssues(doc, russianLanguage),
            legacyIssues: collectLegacyIssues(doc),
            footnoteIssues: collectFootnoteIssues(doc),
            danglingDashIssues: collectDanglingDashIssues(doc),
            widowOrphanIssues: collectWidowOrphanIssues(doc),
            frontMatterFlags: collectFrontMatterFlags(doc)
        };

        if (saveAfter) {
            try {
                doc.save();
                result.saved = true;
            } catch (e) {}
        }

        var reportPath = reportArg;
        if (!reportPath) {
            try {
                reportPath = doc.fullName.fsName.replace(/\.indd$/i, "") + ".layout-qa-report.md";
            } catch (e) {
                reportPath = Folder.desktop.fsName + "/layout-qa-report.md";
            }
        }
        writeReport(reportPath, reportText(result));
        if (reportJsonArg) {
            writeJson(reportJsonArg, result);
        } else {
            writeJson(reportPath.replace(/\.md$/i, ".json"), result);
        }

        restoreInteraction();
    } catch (e) {
        restoreInteraction();
        throw e;
    }
})();
