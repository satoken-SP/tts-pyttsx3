// ラジオボタンの切り替え
document.querySelectorAll('input[name="input-type"]').forEach(radio => {
    radio.addEventListener('change', function() {
        const fileSection = document.getElementById('file-section');
        const textSection = document.getElementById('text-section');
        const folderSection = document.getElementById('folder-section');
        const outputSection = document.getElementById('output-section');

        // すべてのセクションを非アクティブにする
        fileSection.classList.remove('active');
        textSection.classList.remove('active');
        folderSection.classList.remove('active');

        // 出力ファイル名セクションを表示
        outputSection.hidden = false;

        // 選択されたセクションをアクティブにする
        if (this.value === 'file') {
            fileSection.classList.add('active');
        } else if (this.value === 'text') {
            textSection.classList.add('active');
        } else if (this.value === 'folder') {
            folderSection.classList.add('active');
            // フォルダから入力の場合は出力ファイル名を非表示
            outputSection.hidden = true;
        }
    });
});

// ファイル選択時の処理
document.getElementById('file-upload').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (file) {
        document.getElementById('filename-display').value = file.name;
    }
});

// ファイルから変換
async function convertFile() {
    const fileInput = document.getElementById('file-upload');
    const outputFilename = document.getElementById('outputFilename').value;

    if (!fileInput.files[0]) {
        showError('ファイルを選択してください');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('inputType', 'file');
    formData.append('outputFilename', outputFilename);

    // 読み上げ速度を追加
    const selectedRate = document.querySelector('input[name="rate"]:checked').value;
    formData.append('rate', selectedRate);

    await convertTextToSpeech(formData);
}

// テキストから変換
async function convertText() {
    const textInput = document.getElementById('text-input').value.trim();
    const outputFilename = document.getElementById('outputFilename').value;

    if (!textInput) {
        showError('テキストを入力してください');
        return;
    }

    const formData = new FormData();
    formData.append('text', textInput);
    formData.append('inputType', 'text');
    formData.append('outputFilename', outputFilename);

    // 読み上げ速度を追加
    const selectedRate = document.querySelector('input[name="rate"]:checked').value;
    formData.append('rate', selectedRate);

    await convertTextToSpeech(formData);
}

// フォルダから変換
async function convertFolder() {
    const formData = new FormData();
    formData.append('inputType', 'folder');

    // 読み上げ速度を追加
    const selectedRate = document.querySelector('input[name="rate"]:checked').value;
    formData.append('rate', selectedRate);

    await convertTextToSpeech(formData);
}

// 音声変換処理
async function convertTextToSpeech(formData) {
    const loading = document.getElementById('loading');
    const result = document.getElementById('result');

    try {
        loading.classList.add('is-visible');
        result.classList.remove('is-visible');

        const response = await fetch('/convert', {
            method: 'POST',
            headers: { 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            if (data.input_type === 'folder') {
                showSuccess(data.message, null, null, data.total_conversion_time, data.processed_files);
            } else {
                showSuccess(data.message, data.processed_text, data.filename, data.conversion_time, null, data.download_id);
            }
        } else {
            showError(data.error, data.error_id);
        }
    } catch (error) {
        showError('通信に失敗しました。アプリの起動状態を確認して再試行してください。');
    } finally {
        loading.classList.remove('is-visible');
    }
}

// 入力由来の内容はHTMLとして解釈せず、テキストとして表示する。
function createResultElement(tagName, text = '', className = '') {
    const element = document.createElement(tagName);
    element.textContent = text;
    if (className) {
        element.className = className;
    }
    return element;
}

// 成功メッセージ表示
function showSuccess(message, processedText, filename, conversionTime, processedFiles, downloadId) {
    const result = document.getElementById('result');
    result.className = 'result-section result-success';
    result.classList.add('is-visible');

    let headingText = `✅ ${message}`;
    if (conversionTime) {
        headingText += `（変換秒数：${conversionTime}秒）`;
    }
    result.replaceChildren(createResultElement('h4', headingText));

    if (processedText) {
        const container = createResultElement('div', '', 'collapsible-text');
        const header = createResultElement('div', '', 'collapsible-header collapsed');
        header.append(
            createResultElement('span', '変換後のテキストを表示'),
            createResultElement('span', '▼', 'toggle-icon')
        );
        header.addEventListener('click', () => toggleCollapsible(header));
        const content = createResultElement('div', '', 'collapsible-content');
        content.append(createResultElement('div', processedText, 'collapsible-text-content'));
        container.append(header, content);
        result.append(container);
    }

    if (processedFiles) {
        // フォルダ処理の結果表示
        const folderResults = createResultElement('div');
        folderResults.classList.add('spaced-top');
        folderResults.append(createResultElement('h5', '処理結果:'));
        const fileList = createResultElement('div');
        fileList.classList.add('file-result-list');

        processedFiles.forEach(file => {
            const row = createResultElement('div');
            row.classList.add('file-result-row');
            if (file.status === 'success') {
                row.classList.add('file-result-success');
                row.textContent = `✅ ${file.filename} → ${file.output_filename} (${file.conversion_time}秒)`;
            } else {
                row.classList.add('file-result-error');
                row.textContent = `❌ ${file.filename}: ${file.message}`;
                if (file.error_id) row.append(document.createTextNode(` エラーID：${file.error_id}`));
            }
            fileList.append(row);
        });

        folderResults.append(fileList);
        const notice = createResultElement('div');
        notice.classList.add('spaced-top');
        const noticeText = createResultElement('p', '音声ファイルは "output" フォルダに保存されました。');
        noticeText.classList.add('muted-text');
        notice.append(noticeText);
        folderResults.append(notice);
        result.append(folderResults);
    } else if (filename && downloadId) {
        // キャッシュ防止のためタイムスタンプを付与
        const timestamp = Date.now();
        const downloadUrl = `/download/${encodeURIComponent(downloadId)}`;
        const download = createResultElement('div');
        download.classList.add('audio-download');
        const link = createResultElement('a', '音声ファイルをダウンロード', 'btn btn-secondary');
        link.href = downloadUrl;
        const player = document.createElement('audio');
        player.id = 'audio-player';
        player.controls = true;
        player.classList.add('result-audio');
        const source = document.createElement('source');
        source.src = `${downloadUrl}?t=${timestamp}`;
        source.type = 'audio/wav';
        player.append(source, document.createTextNode('お使いのブラウザは audio タグをサポートしていません。'));
        download.append(link, player);
        result.append(download);
    }
}

// エラーメッセージ表示
function showError(message, errorId) {
    const result = document.getElementById('result');
    result.className = 'result-section result-error';
    result.classList.add('is-visible');
    result.replaceChildren(
        createResultElement('h4', '❌ エラー'),
        createResultElement('p', message)
    );
    if (errorId) result.append(createResultElement('p', `エラーID：${errorId}`));
}

// 折りたたみ機能の制御
function toggleCollapsible(header) {
    const content = header.nextElementSibling;
    const isCollapsed = header.classList.contains('collapsed');

    if (isCollapsed) {
        // 展開
        header.classList.remove('collapsed');
        content.classList.add('expanded');
        header.querySelector('span:first-child').textContent = '変換後のテキストを隠す';
    } else {
        // 折りたたみ
        header.classList.add('collapsed');
        content.classList.remove('expanded');
        header.querySelector('span:first-child').textContent = '変換後のテキストを表示';
    }
}

// ラジオボタンの選択状態に応じてスタイルを更新
document.querySelectorAll('.speed-radio-option').forEach(option => {
    const radio = option.querySelector('input[type="radio"]');
    radio.addEventListener('change', () => {
        document.querySelectorAll('.speed-radio-option').forEach(o => o.classList.remove('checked'));
        if (radio.checked) {
            option.classList.add('checked');
        }
    });
    // 初期状態でチェックされているものにスタイルを適用
    if (radio.checked) {
        option.classList.add('checked');
    }
});

document.getElementById('convert-file').addEventListener('click', convertFile);

document.getElementById('convert-text').addEventListener('click', convertText);

document.getElementById('convert-folder').addEventListener('click', convertFolder);
