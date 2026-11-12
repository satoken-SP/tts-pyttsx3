(() => {
    'use strict';
    const byId = id => document.getElementById(id);
    const panel = byId('pronunciation-panel');
    const message = byId('pronunciation-message');
    const audio = byId('pronunciation-audio');
    const manualPanel = byId('manual-pronunciation');
    const manualMessage = byId('manual-pronunciation-message');
    const manualAudio = byId('manual-pronunciation-audio');
    let dictionary = {};
    let excluded = new Set();
    let loading = false;

    function element(tag, text, className) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (className) node.className = className;
        return node;
    }
    function status(node, text, error = false) {
        node.textContent = text;
        node.classList.toggle('pronunciation-error', error);
    }
    function buttonLabel(button, text, icon = '') {
        const symbol = element('span', icon === 'spinner' ? '' : icon, 'pronunciation-action-icon');
        symbol.setAttribute('aria-hidden', 'true');
        symbol.classList.toggle('pronunciation-action-spinner', icon === 'spinner');
        button.replaceChildren(...(icon ? [symbol] : []), document.createTextNode(text));
    }
    async function api(path, body, form = false) {
        const options = body === undefined ? {} : {
            method: 'POST',
            headers: { 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content },
            body: form ? body : JSON.stringify(body)
        };
        if (body !== undefined && !form) options.headers['Content-Type'] = 'application/json';
        let response;
        try { response = await fetch(path, options); }
        catch { throw new Error('通信に失敗しました。アプリの起動状態を確認してください。'); }
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '処理に失敗しました。');
        return data;
    }

    function renderExcluded() {
        const container = byId('excluded-pronunciations');
        container.replaceChildren();
        if (!excluded.size) container.append(element('p', '除外した単語はありません。'));
        for (const word of [...excluded].sort()) {
            const row = element('div', undefined, 'pronunciation-actions');
            const button = element('button', '除外を解除');
            button.type = 'button';
            button.addEventListener('click', async () => {
                button.disabled = true;
                try {
                    await api('/pronunciations/exclude', { term: word, excluded: false });
                    excluded.delete(word);
                    renderExcluded();
                    status(message, `${word} の除外を解除しました。候補の再抽出で再び表示されます。`);
                } catch (error) { status(message, error.message, true); button.disabled = false; }
            });
            row.append(element('span', word), button);
            container.append(row);
        }
    }

    function createCard(candidate, manual = false, registered = false) {
        const ownerPanel = manual ? manualPanel : registered ? byId('pronunciation-source-panel') : panel;
        const player = manual ? manualAudio : registered ? byId('pronunciation-source-audio') : audio;
        const audioLabel = byId(manual ? 'manual-pronunciation-audio-label' : registered ? 'pronunciation-source-audio-label' : 'pronunciation-audio-label');
        const card = element('div', undefined, 'pronunciation-card');
        if (!manual) card.dataset.term = candidate.term;
        const badge = element('span', '', 'pronunciation-badge');
        badge.hidden = true;
        const saveDetails = element('p');
        saveDetails.hidden = true;
        const term = element('input');
        term.type = 'text'; term.maxLength = 120; term.value = candidate.term;
        term.setAttribute('aria-label', '単語');
        const reading = element('input');
        reading.type = 'text'; reading.maxLength = 240; reading.value = candidate.reading;
        reading.placeholder = manual ? '登録する読みを入力してください' : '読み候補がない場合は、読みを入力してください';
        reading.setAttribute('aria-label', `${candidate.term || '指定した単語'}の読み`);
        const sentence = element('textarea');
        sentence.maxLength = 500; sentence.rows = 2;
        sentence.placeholder = '省略すると単語だけを試聴します';
        sentence.setAttribute('aria-label', '試聴する一文');
        if (manual) {
            card.append(badge);
            const termLabel = element('label', '単語'); termLabel.append(term);
            const sentenceLabel = element('label', '試聴する一文（任意）'); sentenceLabel.append(sentence);
            card.append(termLabel, sentenceLabel);
            term.addEventListener('change', () => {
                const word = term.value.trim();
                reading.value = Object.hasOwn(dictionary, word) ? dictionary[word] : '';
                updateSavedState();
                status(rowStatus, Object.hasOwn(dictionary, word) ? '登録済みです。読みを編集して更新できます。' : '未登録の単語です。');
            });
        } else {
            const heading = element('h4', candidate.term);
            const title = element('div', undefined, 'pronunciation-title');
            title.append(heading, badge);
            card.append(title);
            if (candidate.source) card.append(element('small', candidate.source));
            if (!registered) card.append(element('p', candidate.sentence, 'pronunciation-context'));
        }
        const readingLabel = element('label', '読み（編集できます）');
        readingLabel.append(reading); card.append(readingLabel);
        const actions = element('div', undefined, 'pronunciation-actions');
        const rowStatus = element('p', '', 'pronunciation-status');
        rowStatus.setAttribute('role', 'status');
        const exclusionWarning = element('p', '', 'pronunciation-warning');
        exclusionWarning.setAttribute('role', 'status');
        exclusionWarning.hidden = true;
        const pendingExclusions = new Set();
        let busy = false;
        let dismissed = false;
        let savedWord = null, savedReading = null;
        const buttons = new Map();
        function updateSavedState() {
            const saved = savedWord === term.value.trim() && savedReading === reading.value.trim();
            card.classList.toggle('pronunciation-saved', saved);
            badge.hidden = savedWord === null;
            badge.textContent = saved ? '✓ 保存済み' : '未保存の変更あり';
            badge.classList.toggle('pronunciation-dirty', !saved);
            saveDetails.hidden = !saved;
            const save = buttons.get('save');
            if (save) {
                save.button.disabled = busy || dismissed || saved;
                save.button.classList.toggle('pronunciation-complete', saved);
                buttonLabel(save.button, saved ? '保存済み' : save.label, saved ? '✓' : '');
            }
            return saved;
        }
        function addAction(kind, label, pendingLabel, completedLabel, action) {
            const button = element('button', label);
            button.type = 'button';
            button.dataset.action = kind;
            if (kind === 'save' || kind === 'exclude') button.classList.add(`pronunciation-${kind}`);
            buttons.set(kind, { button, label });
            button.addEventListener('click', async () => {
                if (busy) return;
                busy = true;
                card.setAttribute('aria-busy', 'true');
                button.setAttribute('aria-busy', 'true');
                button.classList.remove('pronunciation-complete');
                buttonLabel(button, pendingLabel, 'spinner');
                const controls = [...card.querySelectorAll('button, input, textarea')];
                controls.forEach(node => { node.disabled = true; });
                status(rowStatus, pendingLabel);
                try {
                    await action();
                    buttonLabel(button, completedLabel, '✓');
                    button.classList.add('pronunciation-complete');
                }
                catch (error) {
                    buttonLabel(button, label);
                    status(rowStatus, error.message, true);
                }
                finally {
                    busy = false;
                    card.removeAttribute('aria-busy');
                    button.removeAttribute('aria-busy');
                    controls.forEach(node => { node.disabled = dismissed; });
                    updateSavedState();
                }
            });
            actions.append(button);
            return button;
        }
        function word() {
            const value = term.value.trim();
            if (!value) throw new Error('単語を入力してください。');
            return value;
        }
        async function preview(mode) {
            const currentWord = word();
            if (mode === 'proposed' && !reading.value.trim()) throw new Error('読みを入力してください。');
            const data = await api('/pronunciations/preview', {
                term: currentWord, reading: reading.value.trim(),
                sentence: manual ? (sentence.value.trim() || currentWord) : candidate.sentence,
                mode, rate: Number(document.querySelector('input[name="rate"]:checked').value)
            });
            if (ownerPanel.hidden) return;
            audio.pause(); manualAudio.pause(); byId('pronunciation-source-audio').pause();
            player.src = `/download/${encodeURIComponent(data.download_id)}`;
            player.hidden = false;
            audioLabel.textContent = `${currentWord}：${mode === 'current' ? '現在の読み' : '入力した読み'}で試聴`;
            try { await player.play(); }
            catch { /* Native controls remain available if autoplay is blocked. */ }
            status(rowStatus, '試聴用音声を生成しました。辞書には保存していません。');
        }
        addAction('current', '現在の読みで試聴', '音声を生成中…', '再生できます（現在の読み）', () => preview('current'));
        addAction('proposed', '入力した読みで試聴', '音声を生成中…', '再生できます（入力した読み）', () => preview('proposed'));
        addAction('save', 'この読みで保存', '保存中…', '保存済み', async () => {
            const currentWord = word(), currentReading = reading.value.trim();
            if (!currentReading) throw new Error('読みを入力してください。');
            const before = Object.hasOwn(dictionary, currentWord) ? dictionary[currentWord] : '未登録';
            const result = await api('/pronunciations/save', { term: currentWord, reading: currentReading });
            dictionary[currentWord] = currentReading;
            savedWord = currentWord; savedReading = currentReading;
            saveDetails.textContent = `登録前：${before} → 登録後：${currentReading}`;
            if (result.exclusion_removed === false) {
                pendingExclusions.add(currentWord);
            } else {
                excluded.delete(currentWord);
                pendingExclusions.delete(currentWord);
            }
            updateExclusionWarning(); renderExcluded();
            status(rowStatus, '保存済み。次の音声変換から反映されます。');
        });
        function updateExclusionWarning() {
            exclusionWarning.hidden = pendingExclusions.size === 0;
            exclusionWarning.textContent = pendingExclusions.size
                ? `読みは保存済みです。除外の解除に失敗しました。（対象：${[...pendingExclusions].join('、')}）` : '';
            retryExclusion.hidden = pendingExclusions.size === 0;
            buttonLabel(retryExclusion, '除外解除を再試行');
            retryExclusion.classList.remove('pronunciation-complete');
        }
        const retryExclusion = addAction('retry-exclusion', '除外解除を再試行', '除外解除中…', '除外解除済み', async () => {
            try {
                for (const pendingWord of [...pendingExclusions]) {
                    await api('/pronunciations/exclude', { term: pendingWord, excluded: false });
                    excluded.delete(pendingWord);
                    pendingExclusions.delete(pendingWord);
                }
                status(rowStatus, '除外を解除しました。読みは保存済みです。');
            } finally {
                updateExclusionWarning(); renderExcluded();
            }
        });
        retryExclusion.hidden = true;
        if (!manual && !registered) addAction('exclude', '今後は表示しない', '除外中…', '除外済み', async () => {
            const currentWord = word();
            await api('/pronunciations/exclude', { term: currentWord, excluded: true });
            excluded.add(currentWord); renderExcluded(); dismissed = true;
            status(rowStatus, '除外しました。「今後は表示しない単語を管理」から解除できます。');
        });
        for (const input of [term, reading, sentence]) {
            input.addEventListener('input', () => {
                for (const kind of ['current', 'proposed']) {
                    const record = buttons.get(kind);
                    buttonLabel(record.button, record.label);
                    record.button.classList.remove('pronunciation-complete');
                }
                const saved = updateSavedState();
                status(rowStatus, saved ? '保存済み。次の音声変換から反映されます。' : '未保存の変更あり。');
            });
        }
        card.append(actions, saveDetails, rowStatus, exclusionWarning);
        return card;
    }

    function filterCandidates() {
        const query = byId('pronunciation-filter').value.trim().toLowerCase();
        const cards = [...byId('pronunciation-candidates').children];
        let visible = 0;
        for (const card of cards) {
            card.hidden = !card.dataset.term.toLowerCase().includes(query);
            if (!card.hidden) visible++;
        }
        const count = byId('pronunciation-filter-count');
        count.hidden = cards.length === 0;
        count.textContent = `表示：${visible} / ${cards.length}件${cards.length && !visible ? '（一致する単語はありません）' : ''}`;
    }
    byId('pronunciation-filter').addEventListener('input', filterCandidates);

    async function loadCandidates() {
        if (loading) return;
        loading = true;
        byId('refresh-pronunciations').disabled = true;
        byId('open-pronunciations').disabled = true;
        status(message, '候補を抽出しています。初回は辞書の読み込みに時間がかかります…');
        byId('pronunciation-candidates').replaceChildren();
        filterCandidates();
        try {
            const form = new FormData();
            const mode = document.querySelector('input[name="input-type"]:checked').value;
            form.append('inputType', mode);
            if (mode === 'text') form.append('text', byId('text-input').value);
            if (mode === 'file') {
                const file = byId('file-upload').files[0];
                if (!file) throw new Error('ファイルを選択してください。手動での単語登録も利用できます。');
                form.append('file', file);
            }
            const data = await api('/pronunciations/candidates', form, true);
            for (const candidate of data.candidates) byId('pronunciation-candidates').append(createCard(candidate));
            filterCandidates();
            status(message, data.candidates.length
                ? `${data.candidates.length}件の候補があります。`
                : '未登録の候補はありません。必要な単語は「読み方を単語で登録」から追加できます。');
        } catch (error) { status(message, error.message, true); }
        finally {
            loading = false;
            byId('refresh-pronunciations').disabled = false;
            byId('open-pronunciations').disabled = false;
        }
    }
    async function refreshState() {
        const data = await api('/pronunciations');
        dictionary = Object.assign(Object.create(null), data.dictionary);
        excluded = new Set(data.excluded);
        renderExcluded();
    }
    const sourcePanel = byId('pronunciation-source-panel');
    const sourceMessage = byId('pronunciation-source-message');
    const sourceList = byId('pronunciation-source-list');
    const sourceAudio = byId('pronunciation-source-audio');
    let sourceBusy = false;
    async function loadSource() {
        if (sourceBusy) return;
        sourceBusy = true;
        byId('reload-pronunciation-source').disabled = true;
        byId('open-pronunciation-source').disabled = true;
        sourceList.replaceChildren();
        sourceAudio.pause(); sourceAudio.removeAttribute('src'); sourceAudio.load(); sourceAudio.hidden = true;
        byId('pronunciation-source-audio-label').textContent = '';
        status(sourceMessage, '登録済みの単語を読み込んでいます…');
        try {
            await refreshState();
            const words = Object.entries(dictionary);
            const fragment = document.createDocumentFragment();
            for (const [term, reading] of words) {
                fragment.append(createCard({ term, reading, sentence: term }, false, true));
            }
            sourceList.append(fragment);
            status(sourceMessage, words.length ? `${words.length}件の登録済み単語があります。1語ずつ編集・保存できます。` : '登録済みの単語はありません。「読み方を単語で登録」から追加できます。');
        } catch (error) { status(sourceMessage, error.message, true); }
        finally {
            sourceBusy = false;
            byId('reload-pronunciation-source').disabled = false;
            byId('open-pronunciation-source').disabled = false;
        }
    }
    byId('open-pronunciation-source').addEventListener('click', async () => {
        if (!sourcePanel.hidden) return;
        sourcePanel.hidden = false;
        byId('open-pronunciation-source').setAttribute('aria-expanded', 'true');
        await loadSource();
    });
    byId('reload-pronunciation-source').addEventListener('click', loadSource);
    byId('close-pronunciation-source').addEventListener('click', () => {
        sourceAudio.pause(); sourceAudio.removeAttribute('src'); sourceAudio.load(); sourceAudio.hidden = true;
        byId('pronunciation-source-audio-label').textContent = '';
        sourcePanel.hidden = true;
        byId('open-pronunciation-source').setAttribute('aria-expanded', 'false');
    });
    byId('open-pronunciation-file').addEventListener('click', async () => {
        const button = byId('open-pronunciation-file');
        const feedback = byId('pronunciation-file-message');
        button.disabled = true;
        button.setAttribute('aria-busy', 'true');
        buttonLabel(button, '開いています…', 'spinner');
        feedback.hidden = false;
        status(feedback, '');
        try {
            await api('/pronunciations/open-file', {});
            status(feedback, 'change_library.txtを開きました。保存した変更は次の音声変換から反映されます。');
        } catch (error) { status(feedback, error.message, true); }
        finally {
            button.disabled = false;
            button.removeAttribute('aria-busy');
            buttonLabel(button, 'ファイルを開く');
        }
    });
    byId('open-manual-pronunciation').addEventListener('click', async () => {
        manualPanel.hidden = false;
        byId('open-manual-pronunciation').setAttribute('aria-expanded', 'true');
        byId('open-manual-pronunciation').disabled = true;
        status(manualMessage, '登録済みの単語を読み込んでいます…');
        byId('manual-pronunciation-fields').replaceChildren();
        try {
            await refreshState();
            byId('manual-pronunciation-fields').replaceChildren(createCard({ term: '', reading: '' }, true));
            status(manualMessage, '');
        } catch (error) { status(manualMessage, error.message, true); }
        finally { byId('open-manual-pronunciation').disabled = false; }
    });
    byId('open-pronunciations').addEventListener('click', async () => {
        panel.hidden = false;
        byId('open-pronunciations').setAttribute('aria-expanded', 'true');
        try {
            await refreshState();
            await loadCandidates();
        } catch (error) { status(message, error.message, true); }
    });
    byId('refresh-pronunciations').addEventListener('click', loadCandidates);
    byId('close-pronunciations').addEventListener('click', () => {
        audio.pause(); audio.removeAttribute('src'); audio.load(); audio.hidden = true;
        byId('pronunciation-audio-label').textContent = '';
        panel.hidden = true;
        byId('open-pronunciations').setAttribute('aria-expanded', 'false');
    });
    byId('close-manual-pronunciation').addEventListener('click', () => {
        manualAudio.pause(); manualAudio.removeAttribute('src'); manualAudio.load(); manualAudio.hidden = true;
        byId('manual-pronunciation-audio-label').textContent = '';
        manualPanel.hidden = true;
        byId('open-manual-pronunciation').setAttribute('aria-expanded', 'false');
    });
})();
