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
    let localId = localStorage.getItem('history_ai_tutor_user_id');
    if (!localId) {
        // Числовой ID в диапазоне 900000-999999, чтобы не конфликтовать с реальными Telegram ID
        localId = String(900000 + Math.floor(Math.random() * 100000));
        localStorage.setItem('history_ai_tutor_user_id', localId);
    }
    userId = localId;
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
    practiceContent.innerHTML = '<p class="hint">Генерация задания...</p>';
    try {
        const resp = await fetch(`/api/exam?type=${examType}&user_id=${userId}`);
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
    if (data.options) {
        // ОГЭ — выбор ответа
        let html = `<div class="question">${data.question}</div><div class="options">`;
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
            <div class="question">${data.question}</div>
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
// Темы / База знаний
// ============================================================
const topicsContent = document.getElementById('topics-content');

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

async function loadChronology() {
    topicsContent.innerHTML = '<p class="hint">Загрузка хронологии...</p>';
    try {
        const resp = await fetch('/api/chronology?limit=50');
        const data = await resp.json();
        const events = data.events || [];
        if (!events.length) {
            topicsContent.innerHTML = '<p class="hint">События не найдены.</p>';
            return;
        }
        let html = '<div class="chronology-list">';
        events.forEach(e => {
            html += `<div class="chronology-item"><span class="chrono-date">${e.year || ''}</span> ${e.event || ''}</div>`;
        });
        html += '</div>';
        topicsContent.innerHTML = html;
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки хронологии.</p>';
    }
}

async function loadFigures() {
    topicsContent.innerHTML = '<p class="hint">Загрузка личностей...</p>';
    try {
        const resp = await fetch('/api/figures?limit=50');
        const data = await resp.json();
        const figures = data.figures || [];
        if (!figures.length) {
            topicsContent.innerHTML = '<p class="hint">Личности не найдены.</p>';
            return;
        }
        let html = '<div class="figure-list">';
        figures.forEach(f => {
            html += `<div class="figure-item"><strong>${f.name || ''}</strong> — ${f.description || ''}</div>`;
        });
        html += '</div>';
        topicsContent.innerHTML = html;
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки личностей.</p>';
    }
}

async function loadTerms() {
    topicsContent.innerHTML = '<p class="hint">Загрузка терминов...</p>';
    try {
        const resp = await fetch('/api/terms?limit=50');
        const data = await resp.json();
        const terms = data.terms || [];
        if (!terms.length) {
            topicsContent.innerHTML = '<p class="hint">Термины не найдены.</p>';
            return;
        }
        let html = '<div class="term-list">';
        terms.forEach(t => {
            html += `<div class="term-item"><strong>${t.term || ''}</strong> — ${t.definition || ''}</div>`;
        });
        html += '</div>';
        topicsContent.innerHTML = html;
    } catch (e) {
        topicsContent.innerHTML = '<p class="hint">Ошибка загрузки терминов.</p>';
    }
}

document.getElementById('topics-btn').addEventListener('click', loadTopics);
document.getElementById('chronology-btn').addEventListener('click', loadChronology);
document.getElementById('figures-btn').addEventListener('click', loadFigures);
document.getElementById('terms-btn').addEventListener('click', loadTerms);

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
        content.innerHTML = `
            <div class="placement-result">
                <h3>🎉 Тест уровня пройден!</h3>
                <div class="placement-score">Правильных ответов: ${data.score} из ${data.total}</div>
                <div class="placement-level">Твой уровень: <strong>${data.level}</strong> (${data.rank})</div>
                <p class="hint">Мы подберём задания под твой уровень знаний.</p>
            </div>
        `;
    } catch (e) {
        content.innerHTML = '<p class="hint">Ошибка проверки теста.</p>';
    }
}

document.getElementById('classes-save-btn').addEventListener('click', saveClasses);
document.getElementById('placement-btn').addEventListener('click', startPlacement);
