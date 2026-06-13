// SENA - Android 16 Frontend SPA Controller

document.addEventListener('DOMContentLoaded', () => {
    // --- State & DOM References ---
    let refreshInterval = null;
    let isSyncing = false;

    // Modals
    const ruleDialog = document.getElementById('rule-dialog');
    const credentialsDialog = document.getElementById('credentials-dialog');

    // Forms
    const ruleForm = document.getElementById('rule-form');
    const addContactForm = document.getElementById('add-contact-form');

    // Action Buttons
    const addRuleBtn = document.getElementById('add-rule-btn');
    const closeDialogBtn = document.getElementById('close-dialog-btn');
    const cancelDialogBtn = document.getElementById('cancel-dialog-btn');
    const reconfigureApiBtn = document.getElementById('reconfigure-api-btn');
    const closeCredentialsBtn = document.getElementById('close-credentials-btn');
    const cancelCredentialsBtn = document.getElementById('cancel-credentials-btn');
    const syncNowBtn = document.getElementById('sync-now-btn');
    const clearLogsBtn = document.getElementById('clear-logs-btn');

    // Inputs & Filters
    const ruleTypeSelect = document.getElementById('rule-type');
    const vCleanerToggle = document.getElementById('v-cleaner-toggle');

    // Lists and Containers
    const rulesGrid = document.getElementById('rules-grid');
    const contactsList = document.getElementById('contacts-list');
    const terminalLogs = document.getElementById('terminal-logs');

    // --- Helper Functions ---
    
    // Format ISO timestamp to readable German time (HH:MM:SS)
    function formatTime(isoString) {
        try {
            const date = new Date(isoString);
            return date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) {
            return '--:--:--';
        }
    }

    // Show API setup wizard modal
    if (reconfigureApiBtn) {
        reconfigureApiBtn.addEventListener('click', () => {
            credentialsDialog.showModal();
        });
    }

    // --- Modals Handlers ---
    if (addRuleBtn) {
        addRuleBtn.addEventListener('click', () => {
            ruleForm.reset();
            updateDialogFields();
            loadLabels();
            ruleDialog.showModal();
        });
    }

    if (closeDialogBtn) closeDialogBtn.addEventListener('click', () => ruleDialog.close());
    if (cancelDialogBtn) cancelDialogBtn.addEventListener('click', () => ruleDialog.close());
    
    if (closeCredentialsBtn) closeCredentialsBtn.addEventListener('click', () => credentialsDialog.close());
    if (cancelCredentialsBtn) cancelCredentialsBtn.addEventListener('click', () => credentialsDialog.close());

    // --- Dynamic Form Input Display ---
    if (ruleTypeSelect) {
        ruleTypeSelect.addEventListener('change', updateDialogFields);
    }

    function updateDialogFields() {
        const selectedType = ruleTypeSelect.value;
        
        // Hide all conditional groups first
        document.getElementById('field-sender').style.display = 'none';
        document.getElementById('field-recipient').style.display = 'none';
        document.getElementById('field-subject').style.display = 'none';
        
        // Disable required settings initially on hidden fields
        document.getElementById('rule-sender').removeAttribute('required');
        document.getElementById('rule-recipient').removeAttribute('required');
        document.getElementById('rule-subject').removeAttribute('required');

        if (selectedType === 'from') {
            document.getElementById('field-sender').style.display = 'flex';
            document.getElementById('rule-sender').setAttribute('required', 'true');
        } else if (selectedType === 'to') {
            document.getElementById('field-recipient').style.display = 'flex';
            document.getElementById('rule-recipient').setAttribute('required', 'true');
        } else if (selectedType === 'from_subject') {
            document.getElementById('field-sender').style.display = 'flex';
            document.getElementById('field-subject').style.display = 'flex';
            document.getElementById('rule-sender').setAttribute('required', 'true');
            document.getElementById('rule-subject').setAttribute('required', 'true');
            document.getElementById('rule-subject-label').innerText = 'Betreff-Stichwort';
            document.getElementById('subject-tip').innerText = 'E-Mail muss dieses Stichwort im Betreff tragen.';
        } else if (selectedType === 'subject_keywords') {
            document.getElementById('field-subject').style.display = 'flex';
            document.getElementById('rule-subject').setAttribute('required', 'true');
            document.getElementById('rule-subject-label').innerText = 'Betreff-Stichwörter';
            document.getElementById('subject-tip').innerText = 'Mehrere Wörter können mit Komma getrennt eingegeben werden.';
        }
    }

    // --- API Interactions ---

    // Fetch Rules
    async function loadRules() {
        if (!rulesGrid) return;
        try {
            const response = await fetch('/api/rules');
            if (!response.ok) throw new Error('Failed to fetch rules');
            const rules = await response.json();
            
            if (rules.length === 0) {
                rulesGrid.innerHTML = `
                    <div class="empty-rules-container fade-in">
                        <span class="material-symbols-outlined empty-icon">rule_folder</span>
                        <p>Noch keine Filterregeln angelegt. Erstelle eine neue Regel, um E-Mails zu sortieren.</p>
                    </div>
                `;
                return;
            }

            rulesGrid.innerHTML = rules.map(rule => {
                let conditionText = '';
                if (rule.rule_type === 'from') {
                    conditionText = `Von Absender: <strong>${rule.condition_sender}</strong>`;
                } else if (rule.rule_type === 'to') {
                    conditionText = `An Adresse: <strong>${rule.condition_recipient}</strong>`;
                } else if (rule.rule_type === 'from_subject') {
                    conditionText = `Von: <strong>${rule.condition_sender}</strong> & Betreff: <strong>${rule.condition_subject}</strong>`;
                } else if (rule.rule_type === 'subject_keywords') {
                    conditionText = `Betreff enthält: <strong>${rule.condition_subject}</strong>`;
                }

                const typeLabels = {
                    'from': 'Absender',
                    'to': 'Empfänger',
                    'from_subject': 'Absender & Betreff',
                    'subject_keywords': 'Keywords'
                };

                return `
                    <div class="rule-item-card fade-in" data-id="${rule.id}">
                        <div class="rule-details">
                            <div class="rule-title-row">
                                <span class="rule-title">${rule.name}</span>
                                <span class="rule-type-badge">${typeLabels[rule.rule_type]}</span>
                            </div>
                            <div class="rule-condition">${conditionText}</div>
                            <div class="rule-meta-row">
                                <span class="badge">→ ${rule.target_label}</span>
                                ${rule.remove_from_inbox ? '<span class="badge">Archivieren</span>' : ''}
                                ${rule.remove_from_important ? '<span class="badge">Aus Wichtig</span>' : ''}
                            </div>
                        </div>
                        <div class="rule-actions">
                            <label class="switch-control">
                                <input type="checkbox" class="toggle-rule-active" data-id="${rule.id}" ${rule.active ? 'checked' : ''}>
                                <span class="switch-slider"></span>
                            </label>
                            <button class="icon-button-small delete-rule-btn" data-id="${rule.id}" title="Regel löschen">
                                <span class="material-symbols-outlined">delete</span>
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            // Attach event listeners to toggle switches and delete buttons
            document.querySelectorAll('.toggle-rule-active').forEach(checkbox => {
                checkbox.addEventListener('change', async (e) => {
                    const ruleId = e.target.dataset.id;
                    const active = e.target.checked;
                    await toggleRuleActive(ruleId, active);
                });
            });

            document.querySelectorAll('.delete-rule-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const button = e.currentTarget;
                    const ruleId = button.dataset.id;
                    if (confirm('Möchtest du diese Filterregel wirklich löschen?')) {
                        await deleteRule(ruleId);
                    }
                });
            });

        } catch (error) {
            console.error('Error loading rules:', error);
        }
    }

    // Fetch and populate existing labels in datalist autocomplete
    async function loadLabels() {
        const existingLabelsDatalist = document.getElementById('existing-labels');
        if (!existingLabelsDatalist) return;
        try {
            const response = await fetch('/api/labels');
            if (!response.ok) throw new Error('Failed to fetch labels');
            const labels = await response.json();
            existingLabelsDatalist.innerHTML = labels.map(label => `<option value="${label}">`).join('');
        } catch (error) {
            console.error('Error loading labels:', error);
        }
    }

    // Toggle Rule Active State
    async function toggleRuleActive(ruleId, active) {
        try {
            const response = await fetch(`/api/rules/${ruleId}/toggle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active })
            });
            if (!response.ok) throw new Error('Toggle failed');
            loadLogs();
        } catch (error) {
            console.error(error);
        }
    }

    // Delete Rule
    async function deleteRule(ruleId) {
        try {
            const response = await fetch(`/api/rules/${ruleId}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Delete failed');
            loadRules();
            loadLogs();
        } catch (error) {
            console.error(error);
        }
    }

    // Fetch Settings (Verification clean-up state)
    async function loadSettings() {
        if (!vCleanerToggle) return;
        try {
            const response = await fetch('/api/settings');
            if (!response.ok) throw new Error('Failed to load settings');
            const data = await response.json();
            vCleanerToggle.checked = data.verification_cleanup_enabled;
        } catch (error) {
            console.error(error);
        }
    }

    // Toggle Verification clean-up settings
    if (vCleanerToggle) {
        vCleanerToggle.addEventListener('change', async () => {
            try {
                const response = await fetch('/api/settings/toggle-cleanup', {
                    method: 'POST'
                });
                if (!response.ok) throw new Error('Failed to toggle cleaner');
                loadLogs();
            } catch (error) {
                console.error(error);
            }
        });
    }

    // Fetch Super Wichtig Contacts
    async function loadContacts() {
        if (!contactsList) return;
        try {
            const response = await fetch('/api/contacts');
            if (!response.ok) throw new Error('Failed to fetch contacts');
            const contacts = await response.json();

            if (contacts.length === 0) {
                contactsList.innerHTML = '<li class="empty-list-item">Keine Kontakte geladen</li>';
                return;
            }

            contactsList.innerHTML = contacts.map(c => `
                <li class="fade-in">
                    <div class="contact-info">
                        <span class="contact-email-addr">${c.contact_email}</span>
                        <span class="contact-source">${c.source === 'auto' ? 'Automatisch erkannt' : 'Manuell hinzugefügt'}</span>
                    </div>
                    <button class="icon-button-small delete-contact-btn" data-email="${encodeURIComponent(c.contact_email)}" title="Entfernen">
                        <span class="material-symbols-outlined" style="font-size: 18px;">close</span>
                    </button>
                </li>
            `).join('');

            // Attach event listeners
            document.querySelectorAll('.delete-contact-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const button = e.currentTarget;
                    const email = button.dataset.email;
                    await deleteContact(email);
                });
            });

        } catch (error) {
            console.error(error);
        }
    }

    // Add Contact
    if (addContactForm) {
        addContactForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const emailInput = document.getElementById('contact-email-input');
            const email = emailInput.value.trim();
            if (!email) return;

            try {
                const response = await fetch('/api/contacts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (!response.ok) throw new Error('Add contact failed');
                emailInput.value = '';
                loadContacts();
                loadLogs();
            } catch (error) {
                console.error(error);
            }
        });
    }

    // Delete Contact
    async function deleteContact(emailEncoded) {
        try {
            const response = await fetch(`/api/contacts/${emailEncoded}`, {
                method: 'DELETE'
            });
            if (!response.ok) throw new Error('Delete contact failed');
            loadContacts();
            loadLogs();
        } catch (error) {
            console.error(error);
        }
    }

    // Fetch Logs
    async function loadLogs() {
        if (!terminalLogs) return;
        try {
            const response = await fetch('/api/logs');
            if (!response.ok) throw new Error('Failed to fetch logs');
            const logs = await response.json();

            if (logs.length === 0) {
                terminalLogs.innerHTML = '<div class="log-line log-info"><span class="log-time">--:--:--</span><span class="log-msg">Bisher keine Log-Einträge vorhanden.</span></div>';
                return;
            }

            const isScrolledToBottom = terminalLogs.scrollHeight - terminalLogs.clientHeight <= terminalLogs.scrollTop + 5;

            terminalLogs.innerHTML = logs.map(log => `
                <div class="log-line log-${log.status} fade-in">
                    <span class="log-time">[${formatTime(log.timestamp)}]</span>
                    <span class="log-msg">${log.message}</span>
                </div>
            `).join('');

            // Scroll to bottom if user was already near bottom
            if (isScrolledToBottom) {
                terminalLogs.scrollTop = terminalLogs.scrollHeight;
            }
        } catch (error) {
            console.error(error);
        }
    }

    // Add custom rule submit handler
    if (ruleForm) {
        ruleForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const payload = {
                name: document.getElementById('rule-name').value.trim(),
                rule_type: ruleTypeSelect.value,
                condition_sender: document.getElementById('rule-sender').value.trim() || null,
                condition_recipient: document.getElementById('rule-recipient').value.trim() || null,
                condition_subject: document.getElementById('rule-subject').value.trim() || null,
                target_label: document.getElementById('rule-target-label').value.trim(),
                remove_from_inbox: document.getElementById('rule-remove-inbox').checked,
                remove_from_important: document.getElementById('rule-remove-important').checked
            };

            try {
                const response = await fetch('/api/rules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) throw new Error('Failed to save rule');
                
                ruleDialog.close();
                loadRules();
                loadLogs();
                loadLabels();
            } catch (error) {
                console.error(error);
                alert('Fehler beim Speichern der Regel.');
            }
        });
    }

    // Trigger Manual Sync
    if (syncNowBtn) {
        syncNowBtn.addEventListener('click', async () => {
            if (isSyncing) return;
            
            isSyncing = true;
            syncNowBtn.disabled = true;
            const syncIcon = document.getElementById('sync-icon');
            syncIcon.classList.add('spin');

            try {
                const response = await fetch('/api/trigger-sync', { method: 'POST' });
                if (!response.ok) throw new Error('Sync request failed');
                
                loadLogs();
                // Wait 4 seconds, then reload everything (giving backend worker time to process)
                setTimeout(async () => {
                    await Promise.all([loadRules(), loadContacts(), loadLogs()]);
                    syncIcon.classList.remove('spin');
                    isSyncing = false;
                    syncNowBtn.disabled = false;
                }, 4000);

            } catch (error) {
                console.error(error);
                syncIcon.classList.remove('spin');
                isSyncing = false;
                syncNowBtn.disabled = false;
                alert('Fehler beim Starten der Synchronisation.');
            }
        });
    }

    // Historical Sync Event Handler
    const historicalSyncBtn = document.getElementById('historical-sync-btn');
    const historicalDateInput = document.getElementById('historical-date');

    // Default historical date to 30 days ago
    if (historicalDateInput) {
        const defaultDate = new Date();
        defaultDate.setDate(defaultDate.getDate() - 30);
        historicalDateInput.value = defaultDate.toISOString().split('T')[0];
    }

    if (historicalSyncBtn && historicalDateInput) {
        historicalSyncBtn.addEventListener('click', async () => {
            const sinceDate = historicalDateInput.value;
            if (!sinceDate) {
                alert('Bitte wähle ein Startdatum aus.');
                return;
            }

            historicalSyncBtn.disabled = true;
            const originalText = historicalSyncBtn.innerHTML;
            historicalSyncBtn.innerHTML = `
                <span class="material-symbols-outlined button-icon-spin spin">sync</span>
                Verarbeite...
            `;

            try {
                const response = await fetch('/api/trigger-historical-sync', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ since_date: sinceDate })
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Sync failed');
                }

                loadLogs();
                // Wait 4 seconds, then reload everything (giving backend worker time to start/process)
                setTimeout(async () => {
                    await Promise.all([loadRules(), loadContacts(), loadLogs()]);
                    historicalSyncBtn.innerHTML = originalText;
                    historicalSyncBtn.disabled = false;
                }, 4000);

            } catch (error) {
                console.error(error);
                historicalSyncBtn.innerHTML = originalText;
                historicalSyncBtn.disabled = false;
                alert('Fehler beim Starten des historischen Syncs: ' + error.message);
            }
        });
    }

    // Clear log console (doesn't wipe db, just clears interface or adds log indicator)
    if (clearLogsBtn) {
        clearLogsBtn.addEventListener('click', () => {
            terminalLogs.innerHTML = '<div class="log-line log-info"><span class="log-time">--:--:--</span><span class="log-msg">Konsole geleert.</span></div>';
        });
    }

    // --- Init ---
    async function init() {
        // Only run loaded page API calls if user is authenticated (dashboard grid exists)
        if (document.querySelector('.dashboard-grid')) {
            await Promise.all([
                loadSettings(),
                loadRules(),
                loadContacts(),
                loadLogs(),
                loadLabels()
            ]);
            
            // Auto scroll log to bottom on first load
            if (terminalLogs) {
                terminalLogs.scrollTop = terminalLogs.scrollHeight;
            }

            // Periodically refresh logs, rules, and contacts every 5 seconds
            refreshInterval = setInterval(() => {
                loadLogs();
                // We reload rules and contacts slightly less frequently
                if (Math.random() > 0.8) {
                    loadRules();
                    loadContacts();
                }
            }, 5000);
        }
    }

    init();
});
