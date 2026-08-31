// History AI Tutor — Web App логика

const tg = window.Telegram?.WebApp;
let userId = null;

// Инициализация Telegram Web App
if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#1a1a2e');
    tg.setBackgroundColor('#1a1a2e');
    userId = tg.initDataUnsafe?.user?.id || null;
}

// Fallback: user_id из query-параметра (для тестирования без Telegram)
const urlUserId = new URLSearchParams(window.location.search).get('user_id');
if (!userId && urlUserId) {
    userId = urlUserId;
}

// Fallback: локальный user_id для тестирования без Telegram (стабильный между сессиями)
if (!userId) {
    try {
        let localId = localStorage.getItem('history_ai_tutor_user_id');
        if (!localId) {
            // Числовой ID в диапазоне 900000-999999, чтобы не конфликтовать с реальными Telegram ID
            localId = String(900000 + Math.floor(Math.random() * 100000));
            localStorage.setItem('history_ai_tutor_user_id', localId);
        }
        userId = localId;
    } catch (e) {
        // localStorage недоступен (например, в iframe Telegram WebApp) — генерируем ID на время сессии
        userId = String(900000 + Math.floor(Math.random() * 100000));
    }
}

// ============================================================
// Вкладки
// ============================================================
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        if (tab.dataset.tab === 'profile') loadProfile();
        if (tab.dataset.tab === 'classes') loadClasses();
    });
});

// ============================================================
// Чат
// ============================================================
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');

function addMessage(text, isUser) {
    const div = document.createElement('div');
    div.className = `message ${isUser ? 'user' : 'bot'}`;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;
    div.appendChild(bubble);
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    addMessage(text, true);
    chatInput.value = '';

    // Показываем индикатор печати
    const typing = document.createElement('div');
    typing.className = 'message bot';
    typing.innerHTML = '<div class="bubble typing">...</div>';
    chatMessages.appendChild(typing);

    try {
        const resp = await fetch('/api/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: text, user_id: userId }),
        });
        const data = await resp.json();
        typing.remove();
        addMessage(data.answer || 'Извини, не удалось получить ответ.', false);
    } catch (e) {
        typing.remove();
        addMessage('Ошибка соединения. Попробуй ещё раз.', false);
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// ============================================================
// Практика
// ============================================================
const practiceBtn = document.getElementById('practice-btn');
const practiceContent = document.getElementById('practice-content');

practiceBtn.addEventListener('click', async () => {
    const examType = document.getElementById('exam-type').value;
    const qtype = document.getElementById('exam-qtype').value;
    practiceContent.innerHTML = '<p class="hint">Генерация задания...</p>';
    try {
        const qtypeParam = qtype ? `&qtype=${qtype}` : '';
        const resp = await fetch(`/api/exam?type=${examType}&user_id=${userId}${qtypeParam}`);
        const data = await resp.json();
        renderQuestion(data);
    } catch (e) {
        practiceContent.innerHTML = '<p class="hint">Ошибка генерации задания.</p>';
    }
});

async function submitAnswer(examType, question, answer) {
    try {
        const resp = await fetch('/api/exam/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: examType, user_id: userId, question, answer }),
        });
        return await resp.json();
    } catch (e) {
        return { correct: false, error: 'Ошибка соединения' };
    }
}

function renderQuestion(data) {
    const examType = document.getElementById('exam-type').value;
    if (!data || !data.question) {
        practiceContent.innerHTML = '<p class="hint">Не удалось сгенерировать задание. Попробуй ещё раз.</p>';
        return;
    }
    const fipiBadge = data.fipi_numbers && data.fipi_numbers.length
        ? `<span class="fipi-badge">Задание ${data.fipi_numbers.join(', ')}</span>` : '';
    if (data.options) {
        // ОГЭ — выбор ответа
        let html = `<div class="question">${fipiBadge}${data.question}</div><div class="options">`;
        data.options.forEach((opt, i) => {
            html += `<button class="option" data-idx="${i}" data-correct="${i === data.correct_index}">${i + 1}. ${opt}</button>`;
        });
        html += '</div><div class="explanation" id="explanation"></div>';
        practiceContent.innerHTML = html;

        document.querySelectorAll('.option').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt(btn.dataset.idx, 10);
                const answer = idx + 1; // номер варианта (1-based)
                document.querySelectorAll('.option').forEach(b => b.disabled = true);
                const result = await submitAnswer(examType, data, answer);
                const correct = result.correct;
                if (correct) {
                    btn.classList.add('correct');
                } else {
                    btn.classList.add('wrong');
                    document.querySelector(`.option[data-correct="true"]`).classList.add('correct');
                }
                document.getElementById('explanation').textContent = data.explanation || '';
            });
        });
    } else {
        // ЕГЭ — краткий ответ
        practiceContent.innerHTML = `
            <div class="question">${fipiBadge}${data.question}</div>
            <input type="text" id="ege-answer" placeholder="Введи ответ...">
            <button class="btn-primary" id="ege-check">Проверить</button>
            <div class="explanation" id="explanation"></div>
        `;
        document.getElementById('ege-check').addEventListener('click', async () => {
            const answer = document.getElementById('ege-answer').value.trim();
            const result = await submitAnswer(examType, data, answer);
            const correct = result.correct;
            const expl = document.getElementById('explanation');
            if (correct) {
                expl.textContent = '✅ Верно! ' + (data.explanation || '');
                expl.className = 'explanation correct';
            } else {
                expl.textContent = '❌ Неверно. Правильный ответ: ' + (data.answer || '') + '. ' + (data.explanation || '');
                expl.className = 'explanation wrong';
            }
        });
    }
}

// ============================================================
// Полноценный тест (10 заданий)
// ============================================================
let fullTestQuestions = [];
let fullTestIndex = 0;
let fullTestResults = [];
let fullTestTotalPoints = 0;

const fullTestBtn = document.getElementById('full-test-btn');

fullTestBtn.addEventListener('click', startFullTest);

async function startFullTest() {
    practiceContent.innerHTML = '<p class="hint">Генерация полноценного теста...</p>';
    try {
        const resp = await fetch(`/api/test?user_id=${userId}`);
        const data = await resp.json();
        if (data.error) {
            practiceContent.innerHTML = `<p class="hint">${data.error}</p>`;
            return;
        }
        fullTestQuestions = data.questions || [];
        fullTestIndex = 0;
        fullTestResults = [];
        fullTestTotalPoints = data.total_points || 0;
        if (!fullTestQuestions.length) {
            practiceContent.innerHTML = '<p class="hint">Не удалось сгенерировать тест. Попробуй ещё раз.</p>';
            return;
        }
        renderFullTestQuestion();
    } catch (e) {
        practiceContent.innerHTML = '<p class="hint">Ошибка генерации теста.</p>';
    }
}

function getTypeLabel(type) {
    const labels = {
        'mcq': 'Выбор ответа',
        'short': 'Краткий ответ',
        'source': 'Работа с источником',
        'open': 'Развёрнутый ответ',
    };
    return labels[type] || type;
}

function renderFullTestQuestion() {
    const q = fullTestQuestions[fullTestIndex];
    if (!q) {
        showFullTestResult();
        return;
    }
    const progressPct = Math.round((fullTestIndex / fullTestQuestions.length) * 100);
    const typeLabel = getTypeLabel(q.type);
    let body = '';

    if (q.type === 'mcq' && q.options) {
        // MCQ — выбор ответа
        body = `
            <div class="test-options">
                ${q.options.map((opt, i) => `
                    <button class="test-option" data-idx="${i}" data-correct="${i === q.correct_index}">${i + 1}. ${opt}</button>
                `).join('')}
            </div>
        `;
    } else if (q.type === 'short') {
        // Краткий ответ
        body = `
            <input type="text" class="test-input" id="test-short-answer" placeholder="Введи ответ...">
            <button class="btn-primary" id="test-short-check">Проверить</button>
        `;
    } else if (q.type === 'source') {
        // Развёрнутый ответ по источнику
        body = `
            ${q.source_text ? `<div class="test-source">${q.source_text}</div>` : ''}
            <textarea class="test-textarea" id="test-open-answer" placeholder="Введи развёрнутый ответ..."></textarea>
            <button class="btn-primary" id="test-open-check">Проверить</button>
        `;
    }

    practiceContent.innerHTML = `
        <div class="test-card">
            <div class="test-progress">Вопрос ${fullTestIndex + 1} из ${fullTestQuestions.length}</div>
            <div class="test-progress-bar"><div class="test-progress-fill" style="width:${progressPct}%"></div></div>
            <div>
                <span class="test-type-badge">${typeLabel}</span>
                <span class="test-points">${q.points || 1} балл(а)</span>
            </div>
            <div class="test-question">${q.question}</div>
            ${body}
            <div class="test-feedback" id="test-feedback"></div>
            <div class="test-nav">
                <button class="btn-secondary" id="test-prev" ${fullTestIndex === 0 ? 'disabled' : ''}>← Назад</button>
                <button class="btn-primary" id="test-next" style="display:none">Далее →</button>
            </div>
        </div>
    `;

    // Обработчики
    const prevBtn = document.getElementById('test-prev');
    prevBtn.addEventListener('click', () => {
        if (fullTestIndex > 0) {
            fullTestIndex--;
            renderFullTestQuestion();
        }
    });

    if (q.type === 'mcq' && q.options) {
        document.querySelectorAll('.test-option').forEach(btn => {
            btn.addEventListener('click', async () => {
                const idx = parseInt(btn.dataset.idx, 10);
                const answer = idx + 1; // номер варианта (1-based)
                document.querySelectorAll('.test-option').forEach(b => b.disabled = true);
                const result = await submitFullTestAnswer(q, answer);
                const correct = result.correct;
                if (correct) {
                    btn.classList.add('correct');
                } else {
                    btn.classList.add('wrong');
                    document.querySelector(`.test-option[data-correct="true"]`).classList.add('correct');
                }
                showTestFeedback(result, q);
            });
        });
    } else if (q.type === 'short') {
        document.getElementById('test-short-check').addEventListener('click', async () => {
            const answer = document.getElementById('test-short-answer').value.trim();
            if (!answer) return;
            const result = await submitFullTestAnswer(q, answer);
            showTestFeedback(result, q);
        });
    } else if (q.type === 'source') {
        document.getElementById('test-open-check').addEventListener('click', async () => {
            const answer = document.getElementById('test-open-answer').value.trim();
            if (!answer) return;
            const result = await submitFullTestAnswer(q, answer);
            showTestFeedback(result, q);
        });
    }
}

async function submitFullTestAnswer(q, answer) {
    try {
        const resp = await fetch('/api/test/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, question: q, answer }),
        });
        const data = await resp.json();
        fullTestResults.push({
            question: q,
            user_answer: answer,
            correct: data.correct,
            earned: data.earned || 0,
            points: data.points || 1,
            feedback: data.feedback || '',
        });
        return data;
    } catch (e) {
        fullTestResults.push({
            question: q,
            user_answer: answer,
            correct: false,
            earned: 0,
            points: q.points || 1,
            feedback: 'Ошибка соединения',
        });
        return { correct: false, earned: 0, points: q.points || 1, feedback: 'Ошибка соединения' };
    }
}

function showTestFeedback(result, q) {
    const feedback = document.getElementById('test-feedback');
    const nextBtn = document.getElementById('test-next');
    if (result.correct) {
        feedback.className = 'test-feedback correct';
        feedback.textContent = '✅ Верно! +' + (result.earned || result.points || 1) + ' балл(а)';
    } else {
        feedback.className = 'test-feedback wrong';
        if (q.type === 'source') {
            feedback.textContent = '❌ Неверно. ' + (result.feedback || '') + ' Правильный ответ: ' + (q.answer || '');
        } else {
            feedback.textContent = '❌ Неверно. Правильный ответ: ' + (q.answer || '');
        }
    }
    nextBtn.style.display = 'inline-block';
    nextBtn.addEventListener('click', () => {
        fullTestIndex++;
        renderFullTestQuestion();
    });
}

function showFullTestResult() {
    let totalEarned = 0;
    let totalMax = 0;
    let correctCount = 0;
    fullTestResults.forEach(r => {
        totalEarned += r.earned || 0;
        totalMax += r.points || 1;
        if (r.correct) correctCount++;
    });

    const detailHtml = fullTestResults.map((r, i) => {
        const status = r.correct ? '✅ Верно' : '❌ Неверно';
        const statusClass = r.correct ? 'correct' : 'wrong';
        const correctAnswer = r.question.answer || (r.question.options && r.question.options[r.question.correct_index]) || '';
        return `
            <div class="test-detail-item">
                <div class="test-detail-q">${i + 1}. ${r.question.question}</div>
                <div class="test-detail-status ${statusClass}">${status} · ${r.earned || 0}/${r.points || 1} балл(а)</div>
                ${!r.correct && correctAnswer ? `<div class="test-detail-answer">Правильный ответ: ${correctAnswer}</div>` : ''}
            </div>
        `;
    }).join('');

    practiceContent.innerHTML = `
        <div class="test-result">
            <h3>🎉 Тест завершён!</h3>
            <div class="test-score">Твой результат: <strong>${totalEarned}</strong> из ${totalMax} баллов</div>
            <div class="placement-score">Правильных ответов: ${correctCount} из ${fullTestResults.length}</div>
            <button class="btn-primary" id="test-restart" style="margin-top:12px">🔄 Пройти ещё раз</button>
            <div class="test-detail">
                <h3 style="text-align:left">📋 Разбор ответов</h3>
                ${detailHtml}
            </div>
        </div>
    `;
    document.getElementById('test-restart').addEventListener('click', startFullTest);
}

// ============================================================
// Темы / База знаний
// ============================================================
const topicsContent = document.getElementById('topics-content');
const searchInput = document.getElementById('topics-search-input');

async function loadTopics() {
    topicsContent.innerHTML = '<p class="hint">Загрузка тем...</p>';
    try {
        const resp = await fetch('/api/topics');
        const data = await resp.json();
        const topics = data.topics || [];
        if (!topics.length) {
            topicsContent.innerHTML = '<p class="hint">Темы не найдены.</p>';
            return;
        }
        let html = '<div class="topic-list">';
        topics.forEach(t => {
            html += `<div class="topic-item" data-id="${t.id}">
                <div class="topic-title">${t.title}</div>
                <div class="topic-meta">${t.chunks || 0} чанков · ${t.paragraphs || 0} параграфов</div>
            </div>`;
        });
        html += '</div>';
        topicsContent.innerHTML = html;

        document.querySelectorAll('.topic-item').forEach(item => {
            item.addEventListener('click', async () => {
                const id = item.dataset.id;
                topicsContent.innerHTML = '<p class="hint">Загрузка темы...</p>';
                try {
                    const r = await fetch(`/api/topic/${id}`);
                    const d = await r.json();
                    const paragraphs = d.paragraphs || [];
                    let ph = `<div class="topic-detail"><h3>${d.title || ''}</h3>`;
                    paragraphs.forEach((p, i) => {
                        ph += `<div class="paragraph"><strong>Параграф ${i + 1}</strong><p>${p.text || ''}</p></div>`;
                    });
                    ph += '</div>';
                    topicsContent.innerHTML = ph;
                } catch (e) {
                    topicsContent.innerHTML = '<p class="hint">Ошибка загрузки темы.</p>';
                }
            });
        });
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки тем.</p>';
    }
}

let chronologyData = [];
let figuresData = [];
let termsData = [];

function renderChronology() {
    const q = (searchInput.value || '').trim().toLowerCase();
    const filtered = q ? chronologyData.filter(e => (e.year || '').toLowerCase().includes(q) || (e.event || '').toLowerCase().includes(q)) : chronologyData;
    let html = `<div class="section-count">Событий: ${filtered.length}${q ? ` (из ${chronologyData.length})` : ''}</div>`;
    html += '<div class="chronology-list">';
    filtered.forEach(e => {
        html += `<div class="chronology-item"><span class="chrono-date">${e.year || ''}</span> ${e.event || ''}</div>`;
    });
    html += '</div>';
    topicsContent.innerHTML = html;
}

async function loadChronology() {
    topicsContent.innerHTML = '<p class="hint">Загрузка хронологии...</p>';
    try {
        const resp = await fetch('/api/chronology?limit=2000');
        const data = await resp.json();
        chronologyData = data.events || [];
        if (!chronologyData.length) {
            topicsContent.innerHTML = '<p class="hint">События не найдены.</p>';
            return;
        }
        renderChronology();
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки хронологии.</p>';
    }
}

function renderFigures() {
    const q = (searchInput.value || '').trim().toLowerCase();
    const filtered = q ? figuresData.filter(f => (f.name || '').toLowerCase().includes(q) || (f.description || '').toLowerCase().includes(q)) : figuresData;
    let html = `<div class="section-count">Личностей: ${filtered.length}${q ? ` (из ${figuresData.length})` : ''}</div>`;
    html += '<div class="figure-list">';
    filtered.forEach(f => {
        html += `<div class="figure-item"><strong>${f.name || ''}</strong> — ${f.description || ''}</div>`;
    });
    html += '</div>';
    topicsContent.innerHTML = html;
}

async function loadFigures() {
    topicsContent.innerHTML = '<p class="hint">Загрузка личностей...</p>';
    try {
        const resp = await fetch('/api/figures?limit=2000');
        const data = await resp.json();
        figuresData = data.figures || [];
        if (!figuresData.length) {
            topicsContent.innerHTML = '<p class="hint">Личности не найдены.</p>';
            return;
        }
        renderFigures();
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки личностей.</p>';
    }
}

function renderTerms() {
    const q = (searchInput.value || '').trim().toLowerCase();
    const filtered = q ? termsData.filter(t => (t.term || '').toLowerCase().includes(q) || (t.definition || '').toLowerCase().includes(q)) : termsData;
    let html = `<div class="section-count">Терминов: ${filtered.length}${q ? ` (из ${termsData.length})` : ''}</div>`;
    html += '<div class="term-list">';
    filtered.forEach(t => {
        html += `<div class="term-item"><strong>${t.term || ''}</strong> — ${t.definition || ''}</div>`;
    });
    html += '</div>';
    topicsContent.innerHTML = html;
}

async function loadTerms() {
    topicsContent.innerHTML = '<p class="hint">Загрузка терминов...</p>';
    try {
        const resp = await fetch('/api/terms?limit=2000');
        const data = await resp.json();
        termsData = data.terms || [];
        if (!termsData.length) {
            topicsContent.innerHTML = '<p class="hint">Термины не найдены.</p>';
            return;
        }
        renderTerms();
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки терминов.</p>';
    }
}

function setActiveTopicBtn(btn) {
    document.querySelectorAll('#tab-topics .topics-controls button').forEach(b => {
        b.classList.remove('active');
    });
    btn.classList.add('active');
}

document.getElementById('topics-btn').addEventListener('click', () => {
    setActiveTopicBtn(document.getElementById('topics-btn'));
    loadTopics();
});
document.getElementById('chronology-btn').addEventListener('click', () => {
    setActiveTopicBtn(document.getElementById('chronology-btn'));
    loadChronology();
});
document.getElementById('figures-btn').addEventListener('click', () => {
    setActiveTopicBtn(document.getElementById('figures-btn'));
    loadFigures();
});
document.getElementById('terms-btn').addEventListener('click', () => {
    setActiveTopicBtn(document.getElementById('terms-btn'));
    loadTerms();
});

searchInput.addEventListener('input', () => {
    if (chronologyData.length) renderChronology();
    else if (figuresData.length) renderFigures();
    else if (termsData.length) renderTerms();
});

// ============================================================
// Профиль
// ============================================================
async function loadProfile() {
    const content = document.getElementById('profile-content');
    try {
        const resp = await fetch(`/api/progress?user_id=${userId}`);
        const data = await resp.json();
        const profile = data.profile || {};
        const user = profile.user || {};
        const stats = profile.stats || {};
        const progress = data.progress || {};
        content.innerHTML = `
            <div class="profile-card">
                <div class="profile-name">${user.first_name || 'Ученик'}</div>
                <div class="profile-rank">${profile.rank || 'Новичок'}</div>
                <div class="profile-stats">
                    <div class="stat"><span class="stat-value">${user.level || 1}</span><span class="stat-label">Уровень</span></div>
                    <div class="stat"><span class="stat-value">${user.xp || 0}</span><span class="stat-label">XP</span></div>
                    <div class="stat"><span class="stat-value">${user.streak || 0}🔥</span><span class="stat-label">Серия</span></div>
                    <div class="stat"><span class="stat-value">${stats.accuracy || 0}%</span><span class="stat-label">Точность</span></div>
                </div>
                <div class="achievements">
                    <h3>🏆 Достижения</h3>
                    ${profile.achievements?.length ? profile.achievements.map(a => `<div class="achievement">${a.title}</div>`).join('') : '<p class="hint">Пока нет достижений</p>'}
                </div>
            </div>
        `;
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка загрузки профиля.</p>';
    }
}

// ============================================================
// Карточки (SRS)
// ============================================================
let currentCards = [];
let currentCardIndex = 0;

async function loadCards() {
    const content = document.getElementById('cards-content');
    try {
        const resp = await fetch(`/api/cards?user_id=${userId}`);
        const data = await resp.json();
        currentCards = data.cards || [];
        currentCardIndex = 0;
        const summary = data.summary || {};
        if (!currentCards.length) {
            content.innerHTML = `
                <div class="cards-summary">
                    <p class="hint">🎉 На сегодня карточек нет!</p>
                    <p class="hint">Изучено: ${summary.learned_cards || 0} · Всего: ${summary.total_cards || 0}</p>
                </div>
            `;
            return;
        }
        renderCard();
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка загрузки карточек.</p>';
    }
}

function renderCard() {
    const content = document.getElementById('cards-content');
    const card = currentCards[currentCardIndex];
    if (!card) {
        content.innerHTML = '<p class="hint">🎉 Все карточки на сегодня пройдены!</p>';
        return;
    }
    content.innerHTML = `
        <div class="card-item">
            <div class="card-topic">${card.topic || ''}</div>
            <div class="card-question">${card.question || ''}</div>
            <button id="card-show-answer" class="btn-secondary">Показать ответ</button>
            <div id="card-answer" class="card-answer" style="display:none">
                <p>${card.answer || ''}</p>
                <div class="card-rating">
                    <button class="btn-rating" data-quality="1">😞 Снова</button>
                    <button class="btn-rating" data-quality="3">😕 Сложно</button>
                    <button class="btn-rating" data-quality="5">😊 Легко</button>
                </div>
            </div>
        </div>
    `;
    document.getElementById('card-show-answer').addEventListener('click', () => {
        document.getElementById('card-answer').style.display = 'block';
    });
    document.querySelectorAll('.btn-rating').forEach(btn => {
        btn.addEventListener('click', async () => {
            const quality = parseInt(btn.dataset.quality);
            await reviewCard(card.id, quality);
        });
    });
}

async function reviewCard(cardId, quality) {
    try {
        await fetch('/api/cards/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, card_id: cardId, quality }),
        });
        currentCardIndex++;
        renderCard();
    } catch (e) {
        const content = document.getElementById('cards-content');
        content.innerHTML = '<p class="hint">Ошибка при оценке карточки.</p>';
    }
}

document.getElementById('cards-btn').addEventListener('click', loadCards);

// ============================================================
// Классы и тест уровня
// ============================================================
let selectedClasses = new Set();
let placementQuestions = [];
let placementIndex = 0;
let placementAnswers = [];

async function loadClasses() {
    const listEl = document.getElementById('classes-list');
    try {
        // Загружаем список классов и текущий выбор пользователя
        const [classesResp, userResp] = await Promise.all([
            fetch('/api/classes'),
            fetch(`/api/user/classes?user_id=${userId}`),
        ]);
        const classesData = await classesResp.json();
        const userData = await userResp.json();

        selectedClasses = new Set();
        const saved = userData.classes || 'all';
        if (saved !== 'all') {
            String(saved).split(',').forEach(c => { if (c) selectedClasses.add(parseInt(c)); });
        }

        const classes = classesData.classes || [];
        listEl.innerHTML = `
            <label class="class-option all-option">
                <input type="checkbox" id="class-all" ${saved === 'all' ? 'checked' : ''}>
                <span><strong>Вся база знаний</strong> <small>все классы 5–10</small></span>
            </label>
            ${classes.map(c => `
                <label class="class-option">
                    <input type="checkbox" class="class-checkbox" value="${c.class}"
                        ${saved !== 'all' && selectedClasses.has(c.class) ? 'checked' : ''}>
                    <span><strong>${c.class} класс</strong> <small>${c.description}</small></span>
                </label>
            `).join('')}
        `;

        // Обработчики: выбор "вся база" снимает остальные
        const allCheckbox = document.getElementById('class-all');
        allCheckbox.addEventListener('change', () => {
            if (allCheckbox.checked) {
                document.querySelectorAll('.class-checkbox').forEach(cb => cb.checked = false);
            }
        });
        document.querySelectorAll('.class-checkbox').forEach(cb => {
            cb.addEventListener('change', () => {
                if (cb.checked) allCheckbox.checked = false;
            });
        });
    } catch (e) {
        listEl.innerHTML = '<p class="hint">Ошибка загрузки классов.</p>';
    }
}

async function saveClasses() {
    const allCheckbox = document.getElementById('class-all');
    let classes = 'all';
    if (!allCheckbox.checked) {
        const checked = [...document.querySelectorAll('.class-checkbox:checked')].map(cb => parseInt(cb.value));
        if (checked.length) {
            classes = checked.join(',');
        } else {
            alert('Выбери хотя бы один класс или всю базу знаний.');
            return;
        }
    }
    try {
        const resp = await fetch('/api/user/classes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, classes }),
        });
        const data = await resp.json();
        if (data.status === 'ok') {
            alert('✅ Выбор классов сохранён!');
        } else {
            alert('Ошибка сохранения: ' + (data.error || 'неизвестная'));
        }
    } catch (e) {
        alert('Ошибка соединения при сохранении классов.');
    }
}

async function startPlacement() {
    const content = document.getElementById('placement-content');
    content.innerHTML = '<p class="hint">Генерация теста уровня...</p>';
    try {
        const resp = await fetch(`/api/placement?user_id=${userId}`);
        const data = await resp.json();
        placementQuestions = data.questions || [];
        placementIndex = 0;
        placementAnswers = [];
        if (!placementQuestions.length) {
            content.innerHTML = '<p class="hint">Не удалось сгенерировать тест. Попробуй ещё раз.</p>';
            return;
        }
        renderPlacementQuestion();
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка генерации теста.</p>';
    }
}

function renderPlacementQuestion() {
    const content = document.getElementById('placement-content');
    const q = placementQuestions[placementIndex];
    if (!q) {
        submitPlacement();
        return;
    }
    content.innerHTML = `
        <div class="placement-card">
            <div class="placement-progress">Вопрос ${placementIndex + 1} из ${placementQuestions.length}</div>
            <div class="placement-class">${q.class} класс</div>
            <div class="placement-question">${q.question}</div>
            <div class="placement-options">
                ${q.options.map((opt, i) => `
                    <button class="placement-option" data-index="${i}">${opt}</button>
                `).join('')}
            </div>
        </div>
    `;
    document.querySelectorAll('.placement-option').forEach(btn => {
        btn.addEventListener('click', () => {
            placementAnswers.push({
                question_id: q.id,
                answer_index: parseInt(btn.dataset.index),
            });
            placementIndex++;
            renderPlacementQuestion();
        });
    });
}

async function submitPlacement() {
    const content = document.getElementById('placement-content');
    content.innerHTML = '<p class="hint">Проверка ответов...</p>';
    try {
        const resp = await fetch('/api/placement/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, answers: placementAnswers }),
        });
        const data = await resp.json();
        if (data.error) {
            content.innerHTML = `<p class="hint">${data.error}</p>`;
            return;
        }
        const details = (data.details || []).map((d, i) => {
            const correctOpt = d.options[d.correct_index] || '';
            const userOpt = (d.user_index != null && d.options[d.user_index]) ? d.options[d.user_index] : '—';
            const mark = d.correct ? '✅' : '❌';
            const userLine = d.correct
                ? `<div class="placement-detail-user correct">Ваш ответ: ${userOpt}</div>`
                : `<div class="placement-detail-user wrong">Ваш ответ: ${userOpt}</div>
                   <div class="placement-detail-correct">Правильный ответ: ${correctOpt}</div>`;
            return `
                <div class="placement-detail">
                    <div class="placement-detail-q">${mark} ${i + 1}. ${d.question}</div>
                    ${userLine}
                </div>
            `;
        }).join('');
        content.innerHTML = `
            <div class="placement-result">
                <h3>🎉 Тест уровня пройден!</h3>
                <div class="placement-score">Правильных ответов: ${data.score} из ${data.total}</div>
                <div class="placement-level">Твой уровень: <strong>${data.level}</strong> (${data.rank})</div>
                <p class="hint">Мы подберём задания под твой уровень знаний.</p>
            </div>
            ${details ? `<div class="placement-details"><h4>Разбор ответов</h4>${details}</div>` : ''}
        `;
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка проверки теста.</p>';
    }
}

document.getElementById('classes-save-btn').addEventListener('click', saveClasses);
document.getElementById('placement-btn').addEventListener('click', startPlacement);
