// -------------------------------------------------------------
// App State Variables
// -------------------------------------------------------------
let currentProfile = null;
let availableModels = {};
let currentResults = [];
let progressInterval = null;

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
    const btnBrowseFolder = document.getElementById("btnBrowseFolder");
    const verifyAll = document.getElementById("verifyAll");
    const noVerify = document.getElementById("noVerify");
    const noWeb = document.getElementById("noWeb");
    const btnStartAnalyze = document.getElementById("btnStartAnalyze");
    const progressPanel = document.getElementById("progressPanel");
    const progressStep = document.getElementById("progressStep");
    const progressPercent = document.getElementById("progressPercent");
    const progressBarFill = document.getElementById("progressBarFill");
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

    // Initial Load
    fetchConfig();
    checkLoginStatus();

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

    // 네이티브 폴더 선택 버튼
    btnBrowseFolder.addEventListener("click", openNativeFolderPicker);

    // Start Analysis
    btnStartAnalyze.addEventListener("click", startAnalysis);

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

    // -------------------------------------------------------------
    // 네이티브 폴더 선택 다이얼로그
    // -------------------------------------------------------------
    async function openNativeFolderPicker() {
        // 버튼 비활성화 + 로딩 표시
        btnBrowseFolder.disabled = true;
        const origText = btnBrowseFolder.innerHTML;
        btnBrowseFolder.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" style="animation:spin 1s linear infinite">
                <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
            열는 중...`;

        try {
            const currentVal = submissionsDir.value.trim();
            const url = currentVal
                ? `/api/pick-folder?initial=${encodeURIComponent(currentVal)}`
                : `/api/pick-folder`;
            const res = await fetch(url);
            if (!res.ok) {
                const err = await res.json();
                alert(`폴더 선택 오류: ${err.detail}`);
                return;
            }
            const data = await res.json();
            if (data.path) {
                submissionsDir.value = data.path;
                // 선택 성공 피드백
                submissionsDir.style.borderColor = "var(--color-success)";
                setTimeout(() => { submissionsDir.style.borderColor = ""; }, 1500);
            }
            // data.path === null 이면 취소 - 조용히 무시
        } catch (err) {
            console.error("폴더 선택 API 오류:", err);
            alert("폴더 선택 중 오류가 발생했습니다.");
        } finally {
            btnBrowseFolder.disabled = false;
            btnBrowseFolder.innerHTML = origText;
        }
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
            alert("제출물 폴더 경로를 지정해주세요.");
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
            progressPanel.style.display = "block";
            consoleLogs.innerHTML = `<div class="log-line system-line">> 분석 파이프라인 시동 중...</div>`;
            
            const res = await fetch("/api/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                if (progressInterval) clearInterval(progressInterval);
                progressInterval = setInterval(pollProgress, 1000);
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

    async function pollProgress() {
        try {
            const res = await fetch("/api/analyze/status");
            const state = await res.json();

            progressStep.textContent = state.step;
            progressPercent.textContent = `${state.progress}%`;
            progressBarFill.style.width = `${state.progress}%`;

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
                await fetchLastResults();
                alert("선별 분석 작업이 완료되었습니다!");
            } else if (state.status === "error") {
                clearInterval(progressInterval);
                btnStartAnalyze.disabled = false;
                alert(`분석 중 에러가 발생했습니다: ${state.error_message}`);
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
                    <td colspan="7">조건에 부합하는 분석 데이터가 없습니다.</td>
                </tr>
            `;
            return;
        }

        resultsTableBody.innerHTML = filtered.map(r => {
            let badgeClass = "badge-low";
            if (r.tier === "최우선") badgeClass = "badge-top-priority";
            else if (r.tier === "상") badgeClass = "badge-high";
            else if (r.tier === "중") badgeClass = "badge-medium";

            const ruleScoreStr = r.rule_score !== undefined ? `${r.rule_score}점` : "-";
            const aiScoreStr = r.ai_score !== undefined && r.ai_score !== "ERROR" ? `${r.ai_score}점` : "-";
            const hallScoreStr = r.hallucination_score !== undefined && r.hallucination_score !== "" ? `${r.hallucination_score}점` : "-";

            return `
                <tr>
                    <td style="font-weight: 600;">${escapeHtml(r.student)}</td>
                    <td>${escapeHtml(r.book_title || "미상")}</td>
                    <td>${ruleScoreStr}</td>
                    <td>${aiScoreStr}</td>
                    <td>${hallScoreStr}</td>
                    <td><span class="badge ${badgeClass}">${r.tier}</span></td>
                    <td>
                        <button class="btn btn-sm btn-outline btn-view-detail" data-student="${escapeHtml(r.student)}">
                            상세보기
                        </button>
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
