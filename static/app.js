// -------------------------------------------------------------
// App State Variables
// -------------------------------------------------------------
let currentProfile = null;
let availableModels = {};
let currentResults = [];
let progressInterval = null;
let selectedFiles = [];

// 폴더 브라우저 상태
let folderBrowserState = {
    currentPath: "",
    selectedPath: "",
    parentPath: null
};

// -------------------------------------------------------------
// DOM Elements Initialization
// -------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    // Auth & Header
    const profileStatus = document.getElementById("profileStatus");
    const btnAuthAction = document.getElementById("btnAuthAction");
    const btnTriggerLogin = document.getElementById("btnTriggerLogin");
    const authRequiredPanel = document.getElementById("authRequiredPanel");
    const mainDashboard = document.getElementById("mainDashboard");

    // Modal Auth
    const modalAuth = document.getElementById("modalAuth");
    const btnCloseAuthModal = document.getElementById("btnCloseAuthModal");
    const profileCardsList = document.getElementById("profileCardsList");
    const btnGoToCreateProfile = document.getElementById("btnGoToCreateProfile");

    // Modal Create Profile
    const profileSelectView = document.getElementById("profileSelectView");
    const profileCreateView = document.getElementById("profileCreateView");
    const btnCancelCreateProfile = document.getElementById("btnCancelCreateProfile");
    const btnCreateProfileSubmit = document.getElementById("btnCreateProfileSubmit");

    // Model select on analysis panel
    const selectScreeningProvider = document.getElementById("selectScreeningProvider");
    const selectScreeningModel = document.getElementById("selectScreeningModel");
    const selectVerifyProvider = document.getElementById("selectVerifyProvider");
    const selectVerifyModel = document.getElementById("selectVerifyModel");

    // API Keys list and Batch registration
    const apiKeysList = document.getElementById("apiKeysList");
    const btnOpenBatchKeyModal = document.getElementById("btnOpenBatchKeyModal");
    const btnRefreshModelList = document.getElementById("btnRefreshModelList");

    // Modal Register Key (Batch)
    const modalRegisterKey = document.getElementById("modalRegisterKey");
    const btnCloseRegisterKeyModal = document.getElementById("btnCloseRegisterKeyModal");
    const regGeminiKey = document.getElementById("regGeminiKey");
    const regAnthropicKey = document.getElementById("regAnthropicKey");
    const regOpenaiKey = document.getElementById("regOpenaiKey");
    const btnCancelRegisterKey = document.getElementById("btnCancelRegisterKey");
    const btnRegisterKeySubmit = document.getElementById("btnRegisterKeySubmit");

    // Analysis Panel
    const submissionsDir = document.getElementById("submissionsDir");
    const btnBrowseFile = document.getElementById("btnBrowseFile");
    const selectedFilesBox = document.getElementById("selectedFilesBox");
    const selectedFilesList = document.getElementById("selectedFilesList");
    const selectedFilesCount = document.getElementById("selectedFilesCount");
    const btnClearFiles = document.getElementById("btnClearFiles");
    const centerStatusOverlay = document.getElementById("centerStatusOverlay");
    const verifyAll = document.getElementById("verifyAll");
    const noVerify = document.getElementById("noVerify");
    const noWeb = document.getElementById("noWeb");
    const btnStartAnalyze = document.getElementById("btnStartAnalyze");
    const progressPanel = document.getElementById("progressPanel");
    const progressStep = document.getElementById("centerFrameStep");
    const progressPercent = document.getElementById("centerFramePercent");
    const progressBarFill = document.getElementById("centerFrameBarFill");
    const centerFrameDetail = document.getElementById("centerFrameDetail");
    const consoleLogs = document.getElementById("consoleLogs");


    // Results Panel
    const filterTier = document.getElementById("filterTier");
    const btnExportCSV = document.getElementById("btnExportCSV");
    const resultsTableBody = document.querySelector("#resultsTable tbody");

    // Modal Student Detail
    const modalStudentDetail = document.getElementById("modalStudentDetail");
    const btnCloseDetailModal = document.getElementById("btnCloseDetailModal");
    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabContents = document.querySelectorAll(".tab-content");

    // Task 2: 로컬 도서 인벤토리 패널
    const btnToggleBookInventory = document.getElementById("btnToggleBookInventory");
    const bookInventoryContainer = document.getElementById("bookInventoryContainer");
    const bookInventoryTableBody = document.getElementById("bookInventoryTableBody");
    let bookInventoryExpanded = false;

    // Modal Factsheet Viewer
    const modalFactsheetView = document.getElementById("modalFactsheetView");
    const btnCloseFactsheetModal = document.getElementById("btnCloseFactsheetModal");
    const factsheetViewTitle = document.getElementById("factsheetViewTitle");
    const factsheetViewPath = document.getElementById("factsheetViewPath");
    const factsheetViewHtml = document.getElementById("factsheetViewHtml");

    // Task 5: 단계별 게이팅 버튼
    const btnNextPhase = document.getElementById("btnNextPhase");
    const btnNextPhaseText = document.getElementById("btnNextPhaseText");

    // Initial Load
    fetchConfig();
    checkLoginStatus();
    fetchBookInventory();

    // -------------------------------------------------------------
    // Event Listeners
    // -------------------------------------------------------------
    
    // Auth Modal open/close
    btnAuthAction.addEventListener("click", () => {
        if (currentProfile && currentProfile.logged_in) {
            logout();
        } else {
            openAuthModal();
        }
    });

    btnTriggerLogin.addEventListener("click", openAuthModal);
    btnCloseAuthModal.addEventListener("click", () => modalAuth.style.display = "none");

    // Profile Creation Toggle
    btnGoToCreateProfile.addEventListener("click", () => {
        profileSelectView.style.display = "none";
        profileCreateView.style.display = "block";
    });

    btnCancelCreateProfile.addEventListener("click", () => {
        profileCreateView.style.display = "none";
        profileSelectView.style.display = "block";
    });

    // Create Profile Submit
    btnCreateProfileSubmit.addEventListener("click", createProfile);

    // Provider select change -> update model options
    selectScreeningProvider.addEventListener("change", () => {
        populateModelDropdown("screening", selectScreeningProvider.value, selectScreeningModel);
        saveDefaultModelSelection();
    });
    selectScreeningModel.addEventListener("change", saveDefaultModelSelection);
    
    selectVerifyProvider.addEventListener("change", () => {
        populateModelDropdown("verify", selectVerifyProvider.value, selectVerifyModel);
        saveDefaultModelSelection();
    });
    selectVerifyModel.addEventListener("change", saveDefaultModelSelection);

    // Batch Key Register Modal Trigger
    btnOpenBatchKeyModal.addEventListener("click", openBatchKeyModal);

    // 모델 목록 수동 갱신
    if (btnRefreshModelList) {
        btnRefreshModelList.addEventListener("click", refreshModelList);
    }

    // Key Register modal cancel
    btnCancelRegisterKey.addEventListener("click", () => modalRegisterKey.style.display = "none");
    btnCloseRegisterKeyModal.addEventListener("click", () => modalRegisterKey.style.display = "none");
    btnRegisterKeySubmit.addEventListener("click", submitBatchRegisterKeys);

    if (btnBrowseFile) {
        btnBrowseFile.addEventListener("click", openNativeFilePicker);
    }

    if (btnClearFiles) {
        btnClearFiles.addEventListener("click", () => {
            selectedFiles = [];
            updateSelectedFilesUI();
        });
    }

    // Start Analysis
    btnStartAnalyze.addEventListener("click", startAnalysis);

    // Center Frame Controls
    const btnPauseFrame = document.getElementById("btnPauseFrame");
    const btnStopFrame = document.getElementById("btnStopFrame");
    const btnResetFrame = document.getElementById("btnResetFrame");
    const pauseFrameBtnText = document.getElementById("pauseFrameBtnText");

    if (btnPauseFrame) {
        btnPauseFrame.addEventListener("click", async () => {
            const isPaused = pauseFrameBtnText.textContent.trim() === "재개";
            const endpoint = isPaused ? "/api/analyze/resume" : "/api/analyze/pause";
            try {
                const res = await fetch(endpoint, { method: "POST" });
                if (!res.ok) {
                    const data = await res.json();
                    alert(`요청 실패: ${data.detail}`);
                }
            } catch (err) {
                console.error("일시정지/재개 요청 에러:", err);
            }
        });
    }

    if (btnStopFrame) {
        btnStopFrame.addEventListener("click", async () => {
            if (!confirm("현재 진행 중인 분석 작업을 강제 종료하시겠습니까?")) return;
            try {
                const res = await fetch("/api/analyze/stop", { method: "POST" });
                if (!res.ok) {
                    const data = await res.json();
                    alert(`요청 실패: ${data.detail}`);
                }
            } catch (err) {
                console.error("강제 종료 요청 에러:", err);
            }
        });
    }

    if (btnResetFrame) {
        btnResetFrame.addEventListener("click", async () => {
            try {
                await fetch("/api/analyze/reset", { method: "POST" });
            } catch (err) {
                console.error("초기화 요청 에러:", err);
            }
            switchFrameState("idle");
        });
    }

    // Filter results
    filterTier.addEventListener("change", () => renderResultsTable(currentResults));

    // Export CSV
    btnExportCSV.addEventListener("click", () => {
        window.location.href = "/api/export";
    });

    // Detail Modal Close
    btnCloseDetailModal.addEventListener("click", () => modalStudentDetail.style.display = "none");

    // Tabs switching
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            tabButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));

            btn.classList.add("active");
            const target = btn.dataset.target;
            document.getElementById(target).classList.add("active");
        });
    });

    async function openNativeFilePicker() {
        // 버튼 비활성화 + 로딩 표시
        btnBrowseFile.disabled = true;
        const origText = btnBrowseFile.innerHTML;
        btnBrowseFile.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="animation:spin 1s linear infinite">
                <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
            열리는 중...`;

        try {
            const currentVal = submissionsDir.value.trim();
            const url = currentVal
                ? `/api/pick-file?initial=${encodeURIComponent(currentVal)}`
                : `/api/pick-file`;
            const res = await fetch(url);
            if (!res.ok) {
                const err = await res.json();
                alert(`파일 선택 오류: ${err.detail}`);
                return;
            }
            const data = await res.json();
            if (data.path) {
                const newPaths = data.path.split(';').map(p => p.trim()).filter(p => p);
                newPaths.forEach(p => {
                    if (!selectedFiles.includes(p)) {
                        selectedFiles.push(p);
                    }
                });
                updateSelectedFilesUI();
            }
            // data.path === null 이면 취소 - 조용히 무시
        } catch (err) {
            console.error("파일 선택 API 오류:", err);
            alert("파일 선택 중 오류가 발생했습니다.");
        } finally {
            btnBrowseFile.disabled = false;
            btnBrowseFile.innerHTML = origText;
        }
    }

    function updateSelectedFilesUI() {
        submissionsDir.value = selectedFiles.join(';');
        
        if (selectedFiles.length === 0) {
            selectedFilesBox.style.display = "none";
            selectedFilesList.innerHTML = "";
            selectedFilesCount.textContent = "0";
            return;
        }
        
        selectedFilesBox.style.display = "block";
        selectedFilesCount.textContent = selectedFiles.length;
        
        selectedFilesList.innerHTML = selectedFiles.map((file, index) => {
            const parts = file.split('\\');
            const filename = parts[parts.length - 1];
            return `
                <li>
                    <span class="selected-file-name" title="${escapeHtml(file)}">${escapeHtml(filename)}</span>
                    <button type="button" class="btn-remove-file" data-index="${index}">&times;</button>
                </li>
            `;
        }).join('');
        
        selectedFilesList.querySelectorAll(".btn-remove-file").forEach(btn => {
            btn.addEventListener("click", () => {
                const index = parseInt(btn.dataset.index);
                selectedFiles.splice(index, 1);
                updateSelectedFilesUI();
            });
        });
    }


    // -------------------------------------------------------------
    // Functions
    // -------------------------------------------------------------

    async function fetchConfig() {
        try {
            const res = await fetch("/api/config");
            const data = await res.json();
            availableModels = data.available_models;
            
            // 초기 로딩 후 공급자 드롭다운 갱신
            updateProviderDropdowns();
        } catch (err) {
            console.error("설정 정보 가져오기 실패:", err);
        }
    }

    // API 키 등록 상태에 따라 공급자 드롭다운 제어
    function updateProviderDropdowns() {
        const registeredKeys = (currentProfile && currentProfile.api_keys) || [];

        // 2단계 스크리닝 API 공급자 선택 요소 처리
        Array.from(selectScreeningProvider.options).forEach(opt => {
            opt.disabled = !registeredKeys.includes(opt.value);
        });

        // 3단계 검증 API 공급자 선택 요소 처리
        Array.from(selectVerifyProvider.options).forEach(opt => {
            opt.disabled = !registeredKeys.includes(opt.value);
        });

        // 현재 선택된 값이 미등록 공급자라면, 등록된 첫 번째 공급자로 자동 우회 선택
        const firstRegScreening = Array.from(selectScreeningProvider.options).find(opt => !opt.disabled);
        if (firstRegScreening && (selectScreeningProvider.disabled || selectScreeningProvider.selectedOptions[0]?.disabled)) {
            selectScreeningProvider.value = firstRegScreening.value;
        }
        populateModelDropdown("screening", selectScreeningProvider.value, selectScreeningModel);

        const firstRegVerify = Array.from(selectVerifyProvider.options).find(opt => !opt.disabled);
        if (firstRegVerify && (selectVerifyProvider.disabled || selectVerifyProvider.selectedOptions[0]?.disabled)) {
            selectVerifyProvider.value = firstRegVerify.value;
        }
        populateModelDropdown("verify", selectVerifyProvider.value, selectVerifyModel);
    }

    function populateModelDropdown(type, provider, selectElement) {
        const models = availableModels[provider] || [];
        selectElement.innerHTML = models.map(m => `<option value="${m}">${m}</option>`).join("");
    }

    async function refreshModelList() {
        if (!currentProfile || !currentProfile.logged_in) {
            alert("모델 목록을 갱신하려면 먼저 로그인해주세요.");
            return;
        }

        btnRefreshModelList.disabled = true;
        const origContent = btnRefreshModelList.innerHTML;
        btnRefreshModelList.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="12" height="12" style="margin-right: 4px; animation: spin 1s linear infinite;">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
            </svg>
            갱신 중...`;

        try {
            const res = await fetch("/api/config/refresh", { method: "POST" });
            const data = await res.json();
            
            if (res.ok) {
                // 즉시 설정 로드하여 드롭다운 리렌더링
                await fetchConfig();
                alert(data.message);
            } else {
                alert(`모델 목록 갱신 실패:\n${data.detail || "오류 발생"}`);
            }
        } catch (err) {
            console.error("모델 갱신 API 호출 오류:", err);
            alert("네트워크 통신 중 오류가 발생했습니다.");
        } finally {
            btnRefreshModelList.disabled = false;
            btnRefreshModelList.innerHTML = origContent;
        }
    }

    async function checkLoginStatus() {
        try {
            const res = await fetch("/api/profiles/current");
            const data = await res.json();
            currentProfile = data;
            
            updateHeaderUI();
            if (data.logged_in) {
                renderApiKeysPanel(data.api_keys);
                updateProviderDropdowns(); // API 키 정보를 바탕으로 공급자 활성여부 갱신
                applyDefaultModels(data.default_models);
            }
        } catch (err) {
            console.error("로그인 상태 확인 오류:", err);
        }
    }

    function updateHeaderUI() {
        const indicator = profileStatus.querySelector(".status-indicator");
        const statusText = profileStatus.querySelector(".status-text");

        if (currentProfile && currentProfile.logged_in) {
            indicator.className = "status-indicator online";
            statusText.textContent = `${currentProfile.profile_name}`;
            btnAuthAction.textContent = "로그아웃";
            btnAuthAction.className = "btn btn-sm btn-outline";
            
            authRequiredPanel.style.display = "none";
            mainDashboard.style.display = "grid";
            
            fetchLastResults();
        } else {
            indicator.className = "status-indicator offline";
            statusText.textContent = "로그인 필요";
            btnAuthAction.textContent = "로그인";
            btnAuthAction.className = "btn btn-sm btn-primary";

            mainDashboard.style.display = "none";
            authRequiredPanel.style.display = "block";
        }
    }

    // 대시보드 API 키 현황 요약
    function renderApiKeysPanel(registeredKeys) {
        const providers = [
            { id: "gemini", name: "Google Gemini" },
            { id: "anthropic", name: "Anthropic Claude" },
            { id: "openai", name: "OpenAI GPT" }
        ];

        apiKeysList.innerHTML = providers.map(p => {
            const isReg = registeredKeys.includes(p.id);
            return `
                <div class="api-key-row">
                    <div class="api-key-info">
                        <span class="api-key-name">${p.name}</span>
                        <span class="badge ${isReg ? 'badge-registered' : 'badge-unregistered'}">
                            ${isReg ? '등록됨' : '미등록'}
                        </span>
                    </div>
                    <div class="api-key-actions">
                        <button class="btn-action-key ${isReg ? 'btn-edit-key' : 'btn-register-key'}" data-id="${p.id}">
                            ${isReg ? '수정' : '등록'}
                        </button>
                    </div>
                </div>
            `;
        }).join("");

        // 등록 / 수정 버튼 클릭 이벤트
        document.querySelectorAll(".btn-action-key").forEach(btn => {
            btn.addEventListener("click", () => {
                const id = btn.dataset.id;
                openIndividualKeyModal(id);
            });
        });
    }

    // 개별 키 등록/수정 모달 열기 (특정 공급자 인풋 강조)
    function openIndividualKeyModal(providerId) {
        openBatchKeyModal();
        // 특정 공급자 입력필드 포커스 및 하이라이트
        setTimeout(() => {
            if (providerId === "gemini") {
                regGeminiKey.focus();
                regGeminiKey.style.boxShadow = "0 0 0 2px var(--color-primary)";
                setTimeout(() => { regGeminiKey.style.boxShadow = ""; }, 1500);
            } else if (providerId === "anthropic") {
                regAnthropicKey.focus();
                regAnthropicKey.style.boxShadow = "0 0 0 2px var(--color-primary)";
                setTimeout(() => { regAnthropicKey.style.boxShadow = ""; }, 1500);
            } else if (providerId === "openai") {
                regOpenaiKey.focus();
                regOpenaiKey.style.boxShadow = "0 0 0 2px var(--color-primary)";
                setTimeout(() => { regOpenaiKey.style.boxShadow = ""; }, 1500);
            }
        }, 100);
    }

    function openBatchKeyModal() {
        // 이미 등록된 API가 있으면 플레이스홀더를 마스킹 문자로 대체
        const regKeys = currentProfile ? (currentProfile.api_keys || []) : [];
        
        regGeminiKey.value = "";
        regGeminiKey.placeholder = regKeys.includes("gemini") ? "•••••••••••• (등록 완료, 변경하려면 입력)" : "Gemini Key 입력";
        
        regAnthropicKey.value = "";
        regAnthropicKey.placeholder = regKeys.includes("anthropic") ? "•••••••••••• (등록 완료, 변경하려면 입력)" : "Claude Key 입력";
        
        regOpenaiKey.value = "";
        regOpenaiKey.placeholder = regKeys.includes("openai") ? "•••••••••••• (등록 완료, 변경하려면 입력)" : "GPT Key 입력";
        
        modalRegisterKey.style.display = "flex";
        regGeminiKey.focus();
    }

    async function submitBatchRegisterKeys() {
        const payload = {
            gemini: regGeminiKey.value.trim ? regGeminiKey.value.trim() : regGeminiKey.value,
            anthropic: regAnthropicKey.value.trim ? regAnthropicKey.value.trim() : regAnthropicKey.value,
            openai: regOpenaiKey.value.trim ? regOpenaiKey.value.trim() : regOpenaiKey.value
        };

        // 적어도 하나가 입력되었는지 확인 (단, 새로 수정한 것만 보냄)
        if (!payload.gemini && !payload.anthropic && !payload.openai) {
            alert("변경하거나 새로 입력할 API 키가 없습니다.");
            return;
        }

        try {
            const res = await fetch("/api/profiles/keys/batch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                const data = await res.json();
                alert(data.message);
                modalRegisterKey.style.display = "none";
                await checkLoginStatus();
            } else {
                const data = await res.json();
                alert(`API 키 일괄 등록 실패: ${data.detail}`);
            }
        } catch (err) {
            console.error("일괄 등록 API 오류:", err);
        }
    }

    async function deleteApiKey(provider) {
        try {
            const res = await fetch(`/api/profiles/keys/${provider}`, { method: "DELETE" });
            if (res.ok) {
                alert("API 키가 삭제되었습니다.");
                await checkLoginStatus();
            } else {
                const data = await res.json();
                alert(`API 키 삭제 실패: ${data.detail}`);
            }
        } catch (err) {
            console.error("API 키 삭제 오류:", err);
        }
    }

    function applyDefaultModels(defaults) {
        if (!defaults) return;
        
        if (defaults.screening_provider) {
            selectScreeningProvider.value = defaults.screening_provider;
            populateModelDropdown("screening", defaults.screening_provider, selectScreeningModel);
            if (defaults.screening_model) {
                selectScreeningModel.value = defaults.screening_model;
            }
        }
        
        if (defaults.verify_provider) {
            selectVerifyProvider.value = defaults.verify_provider;
            populateModelDropdown("verify", defaults.verify_provider, selectVerifyModel);
            if (defaults.verify_model) {
                selectVerifyModel.value = defaults.verify_model;
            }
        }
    }

    async function saveDefaultModelSelection() {
        const payload = {
            screening_provider: selectScreeningProvider.value,
            screening_model: selectScreeningModel.value,
            verify_provider: selectVerifyProvider.value,
            verify_model: selectVerifyModel.value
        };

        if (!payload.screening_model || !payload.verify_model) return;

        try {
            await fetch("/api/profiles/select-model", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } catch (err) {
            console.error("디폴트 모델 저장 실패:", err);
        }
    }

    async function openAuthModal() {
        modalAuth.style.display = "flex";
        profileSelectView.style.display = "block";
        profileCreateView.style.display = "none";

        await loadProfilesList();
    }

    async function loadProfilesList() {
        try {
            const res = await fetch("/api/profiles");
            const profiles = await res.json();

            if (profiles.length === 0) {
                profileCardsList.innerHTML = `<p class="text-center" style="color: var(--text-muted); font-size: 13px;">등록된 계정이 없습니다. 먼저 계정을 생성해주세요.</p>`;
                return;
            }

            profileCardsList.innerHTML = profiles.map(p => `
                <div class="profile-card ${p.is_current ? 'active' : ''}" data-name="${p.name}">
                    <div class="profile-meta">
                        <span class="p-name">${p.name}</span>
                        <span class="p-desc">등록된 API: ${p.api_keys.length > 0 ? p.api_keys.join(", ").toUpperCase() : '없음'}</span>
                    </div>
                    <button class="btn-delete-profile" data-name="${p.name}">
                        <svg style="width: 16px; height: 16px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            <line x1="10" y1="11" x2="10" y2="17"></line>
                            <line x1="14" y1="11" x2="14" y2="17"></line>
                        </svg>
                    </button>
                </div>
            `).join("");

            document.querySelectorAll(".profile-card").forEach(card => {
                card.addEventListener("click", async (e) => {
                    if (e.target.closest(".btn-delete-profile")) return;
                    
                    const name = card.dataset.name;
                    await submitLogin(name);
                });
            });

            document.querySelectorAll(".btn-delete-profile").forEach(btn => {
                btn.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    const name = btn.dataset.name;
                    if (confirm(`사용자 계정 '${name}'을(를) 삭제하시겠습니까?`)) {
                        await deleteProfile(name);
                    }
                });
            });

        } catch (err) {
            console.error("프로필 목록 로드 실패:", err);
        }
    }

    async function deleteProfile(name) {
        try {
            const res = await fetch(`/api/profiles/${name}`, { method: "DELETE" });
            if (res.ok) {
                alert("계정이 삭제되었습니다.");
                await loadProfilesList();
                await checkLoginStatus();
            } else {
                const data = await res.json();
                alert(`에러: ${data.detail}`);
            }
        } catch (err) {
            console.error("프로필 삭제 에러:", err);
        }
    }

    async function createProfile() {
        const payload = {
            name: document.getElementById("newProfileName").value.trim ? document.getElementById("newProfileName").value.trim() : document.getElementById("newProfileName").value
        };

        if (!payload.name) {
            alert("사용자 ID를 입력해 주세요.");
            return;
        }

        try {
            const res = await fetch("/api/profiles", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                profileCreateView.style.display = "none";
                modalAuth.style.display = "none";
                
                await submitLogin(payload.name);
            } else {
                const data = await res.json();
                alert(`계정 생성 실패: ${data.detail}`);
            }
        } catch (err) {
            console.error("계정 생성 에러:", err);
        }
    }

    async function submitLogin(profileName) {
        try {
            const res = await fetch("/api/profiles/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: profileName })
            });

            if (res.ok) {
                modalAuth.style.display = "none";
                await checkLoginStatus();
            } else {
                const data = await res.json();
                alert(`로그인 실패: ${data.detail}`);
            }
        } catch (err) {
            console.error("로그인 API 에러:", err);
        }
    }

    async function logout() {
        try {
            const res = await fetch("/api/profiles/logout", { method: "POST" });
            if (res.ok) {
                alert("로그아웃 되었습니다.");
                await checkLoginStatus();
            }
        } catch (err) {
            console.error("로그아웃 에러:", err);
        }
    }

    // -------------------------------------------------------------
    // Analysis Logic
    // -------------------------------------------------------------
    async function startAnalysis() {
        const payload = {
            submissions_dir: submissionsDir.value.trim ? submissionsDir.value.trim() : submissionsDir.value,
            verify_all: verifyAll.checked,
            no_verify: noVerify.checked,
            no_web: noWeb.checked,
            
            screening_provider: selectScreeningProvider.value,
            screening_model: selectScreeningModel.value,
            verify_provider: selectVerifyProvider.value,
            verify_model: selectVerifyModel.value
        };

        if (!payload.submissions_dir) {
            alert("분석할 제출물 파일을 1개 이상 선택해 주세요.");
            return;
        }
        
        const regKeys = currentProfile.api_keys || [];
        if (!regKeys.includes(payload.screening_provider)) {
            alert(`2단계 스크리닝을 위한 ${payload.screening_provider.toUpperCase()} API Key가 등록되어 있지 않습니다. 키를 먼저 등록해 주세요.`);
            return;
        }
        if (!payload.no_verify && !regKeys.includes(payload.verify_provider)) {
            alert(`3단계 검증을 위한 ${payload.verify_provider.toUpperCase()} API Key가 등록되어 있지 않습니다. 키를 먼저 등록해 주세요.`);
            return;
        }

        try {
            btnStartAnalyze.disabled = true;
            consoleLogs.innerHTML = `<div class="log-line system-line">> 분석 파이프라인 시동 중...</div>`;
            
            const res = await fetch("/api/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                // 우측 상태 제어 및 로그 컴포넌트 활성화
                switchFrameState("running");
                progressStep.textContent = "분석 시작 준비 중...";
                centerFrameDetail.textContent = "제출물 데이터를 불러오는 중입니다.";
                progressBarFill.style.width = "0%";
                progressPercent.textContent = "0%";

                const pauseFrameBtnText = document.getElementById("pauseFrameBtnText");
                const pauseFrameIcon = document.getElementById("pauseFrameIcon");
                if (pauseFrameBtnText) pauseFrameBtnText.textContent = "일시정지";
                if (pauseFrameIcon) {
                    pauseFrameIcon.innerHTML = `
                        <rect x="6" y="4" width="4" height="16"></rect>
                        <rect x="14" y="4" width="4" height="16"></rect>
                    `;
                }

                if (progressInterval) clearInterval(progressInterval);
                pollProgress(); // 즉시 한 번 호출하여 2초 대기 딜레이 없이 상태 표시
                progressInterval = setInterval(pollProgress, 2000);
            } else {
                const data = await res.json();
                alert(`분석 시작 실패: ${data.detail}`);
                btnStartAnalyze.disabled = false;
            }
        } catch (err) {
            console.error("분석 API 에러:", err);
            btnStartAnalyze.disabled = false;
        }
    }

    // 우측 상태 제어 및 로그 컴포넌트 조건부 렌더링 상태 제어 함수 (세 개의 메인 패널은 언제나 고정 노출)
    function switchFrameState(stateName) {
        const frameStateIdle = document.getElementById("frameStateIdle");
        const frameStateRunning = document.getElementById("frameStateRunning");
        const frameStateError = document.getElementById("frameStateError");

        if (!frameStateIdle || !frameStateRunning || !frameStateError) return;

        // 모든 서브 컴포넌트를 먼저 숨김
        frameStateIdle.style.display = "none";
        frameStateRunning.style.display = "none";
        frameStateError.style.display = "none";

        if (stateName === "idle" || stateName === "completed" || stateName === "stopped") {
            // 대기/완료 상태: 대기 화면 활성화
            frameStateIdle.style.display = "block";
            
            // 왼쪽 분석 실행 버튼 활성화
            if (btnStartAnalyze) btnStartAnalyze.disabled = false;
        } else if (stateName === "running" || stateName === "paused" || stateName === "awaiting_phase") {
            // 작업 진행 중 상태(단계 게이트 대기 포함): 진행 화면 활성화
            frameStateRunning.style.display = "block";

            // 왼쪽 분석 실행 버튼 비활성화 (동시 실행 방지)
            if (btnStartAnalyze) btnStartAnalyze.disabled = true;
        } else if (stateName === "error") {
            // 에러 발생 상태: 에러 리포트 활성화
            frameStateError.style.display = "block";
            
            // 왼쪽 분석 실행 버튼 비활성화
            if (btnStartAnalyze) btnStartAnalyze.disabled = true;
        }
    }

    async function pollProgress() {
        try {
            const res = await fetch("/api/analyze/status");
            const state = await res.json();

            // 백엔드 상태에 따른 중앙 프레임 조건부 전환
            switchFrameState(state.status);

            if (state.status === "running" || state.status === "paused" || state.status === "awaiting_phase") {
                if (state.step) {
                    progressStep.textContent = state.step;
                }
                progressPercent.textContent = `${state.progress}%`;
                progressBarFill.style.width = `${state.progress}%`;

                // 최근 로그 요약을 상세 상태 영역에 표시
                if (state.logs && state.logs.length > 0) {
                    const cleanLog = state.logs[state.logs.length - 1]
                        .replace(/^[❌✅🎉💾💡▶]\s*/, "")
                        .replace(/^>\s*/, "");
                    centerFrameDetail.textContent = cleanLog;
                }

                // [선별 결과 목록] 실시간 반영: 완료된 학생이 생길 때마다 즉시 테이블에 노출
                await refreshLiveResults();
                // Task 2: 새로 생성된 팩트시트가 있을 수 있으므로 도서 인벤토리도 함께 갱신
                await fetchBookInventory();
            }

            // Task 5: 단계 게이트 대기 상태에서만 [다음 단계 진행] 버튼 활성화
            if (btnNextPhase) {
                btnNextPhase.disabled = state.status !== "awaiting_phase";
                if (btnNextPhaseText) {
                    if (state.status === "awaiting_phase" && state.awaiting_phase === "phase2") {
                        btnNextPhaseText.textContent = "2단계(AI 스크리닝) 진행";
                    } else if (state.status === "awaiting_phase" && state.awaiting_phase === "phase3") {
                        btnNextPhaseText.textContent = "3단계(사실 검증) 진행";
                    } else {
                        btnNextPhaseText.textContent = "다음 단계 진행";
                    }
                }
            }

            // 일시정지 상태에 따른 UI 제어
            const pauseFrameBtnText = document.getElementById("pauseFrameBtnText");
            const pauseFrameIcon = document.getElementById("pauseFrameIcon");
            const spinningIcon = document.querySelector(".spinning-icon");

            if (state.status === "paused") {
                if (pauseFrameBtnText) pauseFrameBtnText.textContent = "재개";
                if (pauseFrameIcon) pauseFrameIcon.innerHTML = `<polygon points="5 3 19 12 5 21 5 3"></polygon>`;
                if (spinningIcon) spinningIcon.style.animationPlayState = "paused";
            } else {
                if (pauseFrameBtnText) pauseFrameBtnText.textContent = "일시정지";
                if (pauseFrameIcon) {
                    pauseFrameIcon.innerHTML = `
                        <rect x="6" y="4" width="4" height="16"></rect>
                        <rect x="14" y="4" width="4" height="16"></rect>
                    `;
                }
                if (spinningIcon) spinningIcon.style.animationPlayState = "running";
            }

            if (state.logs.length > 0) {
                consoleLogs.innerHTML = state.logs.map(log => {
                    let className = "log-line";
                    if (log.startsWith("❌")) className += " text-red";
                    if (log.startsWith("✅") || log.startsWith("🎉")) className += " text-green";
                    if (log.startsWith("[")) className += " system-line";
                    return `<div class="${className}">${escapeHtml(log)}</div>`;
                }).join("");
                consoleLogs.scrollTop = consoleLogs.scrollHeight;
            }

            if (state.status === "completed") {
                clearInterval(progressInterval);
                btnStartAnalyze.disabled = false;
                switchFrameState("idle");
                await fetchLastResults();
                await fetchBookInventory();
                alert("선별 분석 작업이 완료되었습니다!");
            } else if (state.status === "error") {
                clearInterval(progressInterval);
                btnStartAnalyze.disabled = false;
                
                // [에러 발생 상태] 전환 및 메시지 설정
                const frameErrorMessage = document.getElementById("frameErrorMessage");
                if (frameErrorMessage) {
                    frameErrorMessage.textContent = state.error_message || "분석 수행 도중 심각한 에러가 발생했습니다.";
                }
                switchFrameState("error");
            } else if (state.status === "stopped") {
                clearInterval(progressInterval);
                btnStartAnalyze.disabled = false;
                switchFrameState("idle");
                alert("분석 작업이 강제 종료되었습니다.");
            }

        } catch (err) {
            console.error("상태 폴링 오류:", err);
        }
    }

    async function fetchLastResults() {
        try {
            const res = await fetch("/api/results");
            const data = await res.json();
            currentResults = data.results || [];

            updateStatsWidgets(currentResults, data.cost_summary);
            renderResultsTable(currentResults);

            if (currentResults.length > 0) {
                btnExportCSV.disabled = false;
            } else {
                btnExportCSV.disabled = true;
            }

        } catch (err) {
            console.error("결과 가져오기 에러:", err);
        }
    }

    // 분석 진행 중(running/paused)에 [선별 결과 목록]을 실시간으로 갱신한다.
    // 완료(export 가능) 여부 토글은 건드리지 않고 테이블/통계만 반영한다.
    async function refreshLiveResults() {
        try {
            const res = await fetch("/api/results");
            const data = await res.json();
            currentResults = data.results || [];

            updateStatsWidgets(currentResults, data.cost_summary);
            renderResultsTable(currentResults);
        } catch (err) {
            console.error("실시간 결과 갱신 에러:", err);
        }
    }

    // -------------------------------------------------------------
    // Task 2: 로컬 도서 인벤토리 (book_cache.json) 패널
    // -------------------------------------------------------------
    async function fetchBookInventory() {
        try {
            const res = await fetch("/api/book-inventory");
            if (!res.ok) return;
            const data = await res.json();
            renderBookInventory(data.books || []);
        } catch (err) {
            console.error("도서 인벤토리 조회 에러:", err);
        }
    }

    function renderBookInventory(books) {
        if (!bookInventoryTableBody) return;

        if (books.length === 0) {
            bookInventoryTableBody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="4">아직 저장된 도서 팩트시트가 없습니다.</td>
                </tr>
            `;
            return;
        }

        // 접힌 상태(미리보기)에서는 상위 5개만, 펼친 상태에서는 전체를 스크롤 뷰로 렌더
        const previewCount = 5;
        const visibleBooks = bookInventoryExpanded ? books : books.slice(0, previewCount);

        bookInventoryTableBody.innerHTML = visibleBooks.map(b => `
            <tr>
                <td style="font-weight: 600;">${escapeHtml(b.book_title || "미상")}</td>
                <td>${escapeHtml(b.author || "-")}</td>
                <td style="font-size: 11.5px; color: var(--text-muted);">${escapeHtml(b.updated_at || "-")}</td>
                <td>
                    <button class="btn btn-sm btn-outline btn-view-factsheet" data-cache-key="${escapeHtml(b.cache_key)}" data-title="${escapeHtml(b.book_title || "")}">
                        팩트시트 확인
                    </button>
                </td>
            </tr>
        `).join("");

        document.querySelectorAll(".btn-view-factsheet").forEach(btn => {
            btn.addEventListener("click", () => {
                openFactsheetView(btn.dataset.cacheKey, btn.dataset.title);
            });
        });
    }

    if (btnToggleBookInventory) {
        btnToggleBookInventory.addEventListener("click", () => {
            bookInventoryExpanded = !bookInventoryExpanded;
            bookInventoryContainer.classList.toggle("collapsed", !bookInventoryExpanded);
            btnToggleBookInventory.textContent = bookInventoryExpanded ? "접기" : "펼치기";
            fetchBookInventory();
        });
    }

    // 도서의 정확한 팩트시트 파일(로컬 .md)을 즉시 열람 (Task 2: 팩트시트 링커)
    async function openFactsheetView(cacheKey, bookTitle) {
        factsheetViewTitle.textContent = bookTitle || "도서명";
        factsheetViewPath.textContent = "";
        factsheetViewHtml.innerHTML = `<p class="text-center" style="color: var(--text-muted); padding:20px;">팩트시트 파일을 불러오는 중...</p>`;
        modalFactsheetView.style.display = "flex";

        try {
            const res = await fetch(`/api/book-inventory/${encodeURIComponent(cacheKey)}/factsheet`);
            if (res.ok) {
                const data = await res.json();
                factsheetViewTitle.textContent = data.book_title || bookTitle || "도서명";
                factsheetViewPath.textContent = data.file_path ? `📂 ${data.file_path}` : "";
                factsheetViewHtml.innerHTML = data.html || "<p>내용이 없습니다.</p>";
            } else {
                const errData = await res.json();
                factsheetViewHtml.innerHTML = `<p class="text-center" style="color: var(--text-danger); padding:20px;">${escapeHtml(errData.detail || "팩트시트를 찾을 수 없습니다.")}</p>`;
            }
        } catch (err) {
            console.error("팩트시트 열람 에러:", err);
            factsheetViewHtml.innerHTML = `<p class="text-center" style="color: var(--text-danger); padding:20px;">팩트시트 조회 중 통신 에러가 발생했습니다.</p>`;
        }
    }

    if (btnCloseFactsheetModal) {
        btnCloseFactsheetModal.addEventListener("click", () => {
            modalFactsheetView.style.display = "none";
        });
    }

    // Task 5: [다음 단계 진행] 버튼 — 단계 경계 게이트를 해제한다
    if (btnNextPhase) {
        btnNextPhase.addEventListener("click", async () => {
            try {
                btnNextPhase.disabled = true;
                const res = await fetch("/api/analyze/next-phase", { method: "POST" });
                if (!res.ok) {
                    const errData = await res.json();
                    alert(`다음 단계 진행 실패: ${errData.detail || "알 수 없는 오류"}`);
                }
            } catch (err) {
                console.error("다음 단계 진행 API 에러:", err);
            }
        });
    }

    function updateStatsWidgets(results, costSummary) {
        const statTotalStudents = document.getElementById("statTotalStudents");
        const statPriorityStudents = document.getElementById("statPriorityStudents");
        const statEstimatedCost = document.getElementById("statEstimatedCost");

        statTotalStudents.textContent = `${results.length}명`;
        
        const priorityCount = results.filter(r => r.tier === "최우선" || r.tier === "상").length;
        statPriorityStudents.textContent = `${priorityCount}명`;

        if (costSummary && costSummary.total_estimated_cost_usd !== undefined) {
            statEstimatedCost.textContent = `$${costSummary.total_estimated_cost_usd.toFixed(4)}`;
        } else {
            statEstimatedCost.textContent = "$0.0000";
        }
    }

    function renderResultsTable(results) {
        const tier = filterTier.value;
        let filtered = results;

        if (tier !== "all") {
            filtered = results.filter(r => r.tier === tier);
        }

        if (filtered.length === 0) {
            resultsTableBody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">조건에 부합하는 분석 데이터가 없습니다.</td>
                </tr>
            `;
            return;
        }

        resultsTableBody.innerHTML = filtered.map(r => {
            let badgeClass = "badge-low";
            if (r.tier === "최우선") badgeClass = "badge-top-priority";
            else if (r.tier === "상") badgeClass = "badge-high";
            else if (r.tier === "중") badgeClass = "badge-medium";

            const studentIdStr = r.student_id ? escapeHtml(r.student_id) : "-";
            const studentNameStr = escapeHtml(r.student_name || r.student || "-");

            // 1단계 결과: stage1_rules(토큰 비소비)가 이미 끝났는지 여부로 표시
            const stage1Str = r.rule_score !== undefined
                ? `${r.rule_score}점`
                : `<span style="color: var(--text-muted);">대기중</span>`;

            // 2단계 결과: 아직 AI 스크리닝 전이면 "대기중" (1단계만 끝난 실시간 상태 표현)
            const stage2Str = (r.ai_score !== undefined && r.ai_score !== "ERROR")
                ? `${r.ai_score}점${(r.stage2 && r.stage2.error) ? " ⚠️" : ""}`
                : `<span style="color: var(--text-muted);">대기중</span>`;

            // 3단계 결과: stage3 데이터가 없으면 "미실시"(대상 아님/생략), 있으면 모순 건수·할루점수 표시
            let stage3Str = `<span style="color: var(--text-muted);">미실시</span>`;
            if (r.stage3 && Object.keys(r.stage3).length > 0) {
                const hall = r.hallucination_score !== undefined && r.hallucination_score !== "" ? r.hallucination_score : (r.stage3.hallucination_score ?? "-");
                const contradictions = r.contradictions || 0;
                stage3Str = contradictions > 0
                    ? `<span style="color: var(--color-danger); font-weight:600;">모순 ${contradictions}건 (할루 ${hall}점)</span>`
                    : `할루 ${hall}점`;
            }

            return `
                <tr>
                    <td style="font-weight: 600;">${studentIdStr}</td>
                    <td style="font-weight: 600;">${studentNameStr}</td>
                    <td>${escapeHtml(r.book_title || "미상")}</td>
                    <td>${stage1Str}</td>
                    <td>${stage2Str}</td>
                    <td>${stage3Str}</td>
                    <td><span class="badge ${badgeClass}">${r.tier || "-"}</span></td>
                    <td>
                        <div style="display: flex; gap: 6px;">
                            <button class="btn btn-sm btn-outline btn-view-detail" data-student="${escapeHtml(r.student)}">
                                상세보기
                            </button>
                            <button class="btn btn-sm btn-success btn-enrich-factsheet" data-title="${escapeHtml(r.book_title || '')}" data-author="${escapeHtml(r.author || r.stage2?.author || '')}">
                                팩트시트 보강
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");

        document.querySelectorAll(".btn-view-detail").forEach(btn => {
            btn.addEventListener("click", () => {
                const student = btn.dataset.student;
                openStudentDetail(student);
            });
        });

        document.querySelectorAll(".btn-enrich-factsheet").forEach(btn => {
            btn.addEventListener("click", async () => {
                const bookTitle = btn.dataset.title;
                const author = btn.dataset.author;

                if (!bookTitle) {
                    alert("도서 정보가 존재하지 않습니다.");
                    return;
                }

                try {
                    btn.disabled = true;
                    btn.textContent = "보강 중...";

                    const res = await fetch("/api/analyze/enrich-factsheet", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ book_title: bookTitle, author: author })
                    });

                    if (res.ok) {
                        const consoleLogs = document.getElementById("consoleLogs");
                        if (consoleLogs) {
                            const timeStr = new Date().toLocaleTimeString();
                            const logDiv = document.createElement("div");
                            logDiv.className = "log-line info-line";
                            logDiv.textContent = `> [${timeStr}] 팩트시트 보강 완료 (${bookTitle} - ${author || '저자 미상'})`;
                            consoleLogs.appendChild(logDiv);
                            consoleLogs.scrollTop = consoleLogs.scrollHeight;
                        }
                        btn.textContent = "보강 완료";
                    } else {
                        const errData = await res.json();
                        alert(`보강 실패: ${errData.detail || '알 수 없는 오류'}`);
                        btn.disabled = false;
                        btn.textContent = "팩트시트 보강";
                    }
                } catch (err) {
                    console.error("보강 API 통신 에러:", err);
                    alert("보강 중 통신 에러가 발생했습니다.");
                    btn.disabled = false;
                    btn.textContent = "팩트시트 보강";
                }
            });
        });
    }

    // -------------------------------------------------------------
    // Student Detail Modal
    // -------------------------------------------------------------
    async function openStudentDetail(studentName) {
        const data = currentResults.find(r => r.student === studentName);
        if (!data) return;

        document.getElementById("detailStudentName").textContent = studentName;
        document.getElementById("detailRuleScore").textContent = data.rule_score !== undefined ? data.rule_score : "-";
        document.getElementById("detailAIScore").textContent = data.ai_score !== undefined ? data.ai_score : "-";
        
        const stage3 = data.stage3 || {};
        document.getElementById("detailHallScore").textContent = stage3.hallucination_score !== undefined ? `${stage3.hallucination_score}%` : "-";

        const banner = document.getElementById("detailTierBanner");
        banner.textContent = `판정 등급: ${data.tier}`;
        banner.className = "tier-banner";
        if (data.tier === "최우선") banner.classList.add("badge-top-priority");
        else if (data.tier === "상") banner.classList.add("badge-high");
        else if (data.tier === "중") banner.classList.add("badge-medium");
        else banner.classList.add("badge-low");

        const detailRuleEvidence = document.getElementById("detailRuleEvidence");
        const details = data.rule_details || {};
        let evidenceList = [];
        for (const [checkName, checkObj] of Object.entries(details)) {
            if (checkObj.score > 0) {
                let desc = `[${checkName}] ${checkObj.score}점`;
                if (checkObj.evidence && checkObj.evidence.length > 0) {
                    const sample = checkObj.evidence[0];
                    if (sample.phrase) desc += ` (감지 상투구: "${sample.phrase}")`;
                    if (sample.pattern_name) desc += ` (감지 정규식 패턴: ${sample.pattern_name})`;
                    if (sample.type) desc += ` (감지 종류: ${sample.type})`;
                }
                evidenceList.push(`<li>${escapeHtml(desc)}</li>`);
            }
        }
        detailRuleEvidence.innerHTML = evidenceList.length > 0 ? evidenceList.join("") : "<li>검출된 자동 규칙 위반 증거가 없습니다.</li>";

        const stage2 = data.stage2 || {};
        const detailAISignals = document.getElementById("detailAISignals");
        const signals = stage2.signals || [];
        detailAISignals.innerHTML = signals.length > 0 ? signals.map(s => `<span class="signal-badge">${escapeHtml(s)}</span>`).join("") : `<span style="color: var(--text-muted); font-size:11px;">감지 신호 없음</span>`;
        document.getElementById("detailAIRationale").textContent = stage2.rationale || "감지 판정 소견이 없습니다.";

        const detailFactClaimsTable = document.querySelector("#detailFactClaimsTable tbody");
        const claims = stage3.claims || [];
        if (claims.length > 0) {
            detailFactClaimsTable.innerHTML = claims.map(c => {
                let vClass = "badge-low";
                if (c.verdict === "모순") vClass = "badge-high";
                else if (c.verdict === "판단불가") vClass = "badge-medium";

                return `
                    <tr>
                        <td style="font-weight:500;">${escapeHtml(c.claim)}</td>
                        <td><span class="badge ${vClass}">${c.verdict}</span></td>
                        <td>${escapeHtml(c.explanation || "-")}</td>
                        <td style="font-style: italic; color: var(--text-secondary);">${escapeHtml(c.factsheet_basis || "-")}</td>
                    </tr>
                `;
            }).join("");
        } else {
            detailFactClaimsTable.innerHTML = `
                <tr>
                    <td colspan="4" class="text-center" style="color: var(--text-muted); padding: 20px;">검증된 사실 주장이 없습니다. (3단계를 통과하지 않았거나 대상이 아닙니다)</td>
                </tr>
            `;
        }

        const detailQuestions = document.getElementById("detailQuestions");
        const questions = stage3.interview_questions || [];
        detailQuestions.innerHTML = questions.length > 0 ? questions.map(q => `<li>${escapeHtml(q)}</li>`).join("") : "<li>추천된 구술 면담 질문이 없습니다.</li>";

        document.getElementById("detailOriginalText").textContent = data.text || "";

        const detailReportMarkdownHtml = document.getElementById("detailReportMarkdownHtml");
        detailReportMarkdownHtml.innerHTML = `<p class="text-center" style="color: var(--text-muted); padding:20px;">상세 마크다운 보고서 파일을 로딩 중...</p>`;
        
        tabButtons.forEach(b => b.classList.remove("active"));
        tabContents.forEach(c => c.classList.remove("active"));
        tabButtons[0].classList.add("active");
        tabContents[0].classList.add("active");

        modalStudentDetail.style.display = "flex";

        try {
            const res = await fetch(`/api/reports/${data.student}`);
            if (res.ok) {
                const rep = await res.json();
                detailReportMarkdownHtml.innerHTML = rep.html;
            } else {
                detailReportMarkdownHtml.innerHTML = `<p class="text-center" style="color: var(--text-danger); padding:20px;">주의/상 등급 미달 또는 파일 손상으로 개별 보고서 파일이 부재합니다.</p>`;
            }
        } catch (err) {
            console.error("보고서 파일 로딩 에러:", err);
            detailReportMarkdownHtml.innerHTML = `<p class="text-center" style="color: var(--text-danger); padding:20px;">마크다운 보고서를 가져올 수 없습니다.</p>`;
        }
    }

    // Resizable Splitter Logic for live analysis logs
    const progressPanelResizer = document.getElementById("progressPanelResizer");
    if (progressPanelResizer) {
        let startY, startHeight;
        
        progressPanelResizer.addEventListener("mousedown", (e) => {
            startY = e.clientY;
            startHeight = consoleLogs.clientHeight;
            
            document.addEventListener("mousemove", doDrag);
            document.addEventListener("mouseup", stopDrag);
            progressPanelResizer.classList.add("dragging");
            e.preventDefault();
        });
        
        function doDrag(e) {
            const newHeight = startHeight + (e.clientY - startY);
            if (newHeight >= 120 && newHeight <= 800) {
                consoleLogs.style.height = `${newHeight}px`;
            }
        }
        
        function stopDrag() {
            document.removeEventListener("mousemove", doDrag);
            document.removeEventListener("mouseup", stopDrag);
            progressPanelResizer.classList.remove("dragging");
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        return str.toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
});
