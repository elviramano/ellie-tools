import Cocoa

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let input = NSTextField()
    let status = NSTextField(wrappingLabelWithString: "Вставьте ссылку на видео YouTube.")
    let folderLabel = NSTextField(wrappingLabelWithString: "")
    let language = NSPopUpButton()
    let saveButton = NSButton(title: "Сохранить транскрипт", target: nil, action: nil)
    let folderButton = NSButton(title: "Выбрать папку…", target: nil, action: nil)
    let progress = NSProgressIndicator()
    var output = ""
    var support: URL {
        if let path = Bundle.main.object(forInfoDictionaryKey: "YTSupportDirectory") as? String {
            return URL(fileURLWithPath: path)
        }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/YouTube Transcripts")
    }
    var python: URL { support.appendingPathComponent("venv/bin/python") }
    var script: URL { Bundle.main.resourceURL!.appendingPathComponent("transcripts.py") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Завершить YouTube Transcripts", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "Правка")
        editMenu.addItem(withTitle: "Вырезать", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Копировать", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Вставить", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Выбрать всё", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 710, height: 410), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "YouTube Transcripts"
        window.center()
        let content = window.contentView!
        func add(_ view: NSView, _ x: CGFloat, _ y: CGFloat, _ w: CGFloat, _ h: CGFloat) {
            view.frame = NSRect(x: x, y: y, width: w, height: h)
            content.addSubview(view)
        }
        let heading = NSTextField(labelWithString: "Подкаст → Markdown")
        heading.font = .systemFont(ofSize: 24, weight: .semibold)
        add(heading, 28, 350, 650, 34)
        let subtitle = NSTextField(labelWithString: "Полный текст субтитров · таймкоды · без пересказа")
        subtitle.textColor = .secondaryLabelColor
        add(subtitle, 28, 323, 650, 22)
        input.placeholderString = "https://youtu.be/…"
        input.font = .systemFont(ofSize: 15)
        input.target = self
        input.action = #selector(save)
        add(input, 28, 270, 538, 30)
        let paste = NSButton(title: "Вставить", target: self, action: #selector(pasteURL))
        add(paste, 578, 268, 105, 34)
        language.addItems(withTitles: ["Исходный язык — автоматически", "English", "Русский"])
        add(language, 28, 222, 305, 30)
        saveButton.target = self
        saveButton.action = #selector(save)
        saveButton.keyEquivalent = "\r"
        add(saveButton, 452, 220, 232, 34)
        progress.style = .spinning
        progress.isDisplayedWhenStopped = false
        add(progress, 421, 225, 20, 20)
        status.font = .systemFont(ofSize: 13)
        add(status, 28, 128, 650, 78)
        folderLabel.font = .systemFont(ofSize: 11)
        folderLabel.textColor = .secondaryLabelColor
        add(folderLabel, 28, 67, 650, 52)
        folderButton.target = self
        folderButton.action = #selector(chooseFolder)
        add(folderButton, 24, 22, 155, 32)
        let open = NSButton(title: "Открыть папку", target: self, action: #selector(openFolder))
        add(open, 529, 22, 155, 32)
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(input)
        NSApp.activate(ignoringOtherApps: true)
        run(["--get-output"]) { result in
            if let folder = result["output_dir"] as? String {
                self.setFolder(folder)
                if result["configured"] as? Bool == false { self.chooseFolder() }
            }
            else { self.show(result) }
        }
    }

    func setFolder(_ path: String) {
        output = path
        folderLabel.stringValue = "Сохранять в:\n" + path
    }
    func show(_ result: [String: Any]) {
        let failed = result["status"] as? String == "error"
        status.textColor = failed ? .systemRed : .labelColor
        var text = result["message"] as? String ?? "Не удалось получить результат."
        if let path = result["path"] as? String { text += "\n" + URL(fileURLWithPath: path).lastPathComponent }
        status.stringValue = text
    }
    @objc func pasteURL() {
        if let text = NSPasteboard.general.string(forType: .string) {
            input.stringValue = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
    @objc func save() {
        guard saveButton.isEnabled else { return }
        let url = input.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { status.stringValue = "Сначала вставьте ссылку YouTube."; return }
        saveButton.isEnabled = false
        folderButton.isEnabled = false
        progress.startAnimation(nil)
        status.textColor = .secondaryLabelColor
        status.stringValue = "Получаю субтитры и сохраняю файл…"
        let code = ["auto", "en", "ru"][language.indexOfSelectedItem]
        run(["--language", code, "--", url]) { result in
            self.progress.stopAnimation(nil)
            self.saveButton.isEnabled = true
            self.folderButton.isEnabled = true
            self.show(result)
        }
    }
    @objc func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Выбрать"
        if !output.isEmpty { panel.directoryURL = URL(fileURLWithPath: output) }
        panel.beginSheetModal(for: window) { response in
            if response == .OK, let url = panel.url {
                self.run(["--set-output", url.path]) { result in
                    if let folder = result["output_dir"] as? String { self.setFolder(folder) }
                    else { self.show(result) }
                }
            }
        }
    }
    @objc func openFolder() {
        if !output.isEmpty { NSWorkspace.shared.open(URL(fileURLWithPath: output)) }
    }
    func run(_ arguments: [String], completion: @escaping ([String: Any]) -> Void) {
        let executable = python
        let source = script
        DispatchQueue.global(qos: .userInitiated).async {
            let task = Process()
            task.executableURL = executable
            task.arguments = [source.path] + arguments
            var environment = ProcessInfo.processInfo.environment
            environment["YOUTUBE_TRANSCRIPTS_HOME"] = executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().path
            task.environment = environment
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = FileHandle.nullDevice
            do {
                try task.run()
                let timeout = DispatchWorkItem { if task.isRunning { task.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + 180, execute: timeout)
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                timeout.cancel()
                let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                DispatchQueue.main.async {
                    completion(result ?? ["status": "error", "message": "Загрузка прервалась или заняла больше трёх минут. Повторите позже."])
                }
            } catch {
                DispatchQueue.main.async {
                    completion(["status": "error", "message": "Не найден установленный загрузчик. Повторно запустите установку YouTube Transcripts."])
                }
            }
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
