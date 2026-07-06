// -------------------------------------------------------------
// App State Variables
// -------------------------------------------------------------
let currentProfile = null;
let availableModels = {};
let currentResults = [];
let pollTimer = null; // 상태 적응형 폴링 타이머 (setTimeout 핸들 — 고정 setInterval 사용 금지)
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
    const btnImportCSV = document.getElementById("btnImportCSV");
    const inputImportCSV = document.getElementById("inputImportCSV");
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

    // 3단계 검증 대상 선택 모달 (듀얼 패널 Transfer List)
    const modalStage3Select = document.getElementById("modalStage3Select");
    const btnCloseStage3Modal = document.getElementById("btnCloseStage3Modal");
    const stage3LeftList = document.getElementById("stage3LeftList");
    const stage3RightList = document.getElementById("stage3RightList");
    const stage3LeftCount = document.getElementById("stage3LeftCount");
    const stage3RightCount = document.getElementById("stage3RightCount");
    const stage3SelectSummary = document.getElementById("stage3SelectSummary");
    const btnStage3SelectAll = document.getElementById("btnStage3SelectAll");
    const btnStage3ClearAll = document.getElementById("btnStage3ClearAll");
    const btnStage3Confirm = document.getElementById("btnStage3Confirm");
    const btnStage3Skip = document.getElementById("btnStage3Skip");

    // 3단계 선택 상태 (백엔드 awaiting_stage3_selection 페이로드 기반)
    let stage3Candidates = [];          // 전체 후보 (이전 단계 결과 요약 포함)
    let stage3SelectedSet = new Set();  // 우측 패널(검증 대상)에 있는 학생 키
    let stage3ModalAutoOpened = false;   // 대기 상태 진입 시 1회 자동 오픈 플래그
    let lastPipelineStatus = "";         // btnNextPhase 클릭 분기용
    let activeProject = null;            // 활성 프로젝트 {project_id, name} — activate 성공 시에만 설정
    let lastGeneratingActive = false;    // 팩트시트 생성 활성 → 비활성 전환 감지용 (인벤토리 Event-Driven 갱신)

    // 세션 진행 상태 파일 UI (State Portability)
    const sessionFileName = document.getElementById("sessionFileName");
    const sessionFilePath = document.getElementById("sessionFilePath");
    const btnDownloadSession = document.getElementById("btnDownloadSession");
    const btnUploadSession = document.getElementById("btnUploadSession");
    const inputUploadSession = document.getElementById("inputUploadSession");

    // Initial Load
    fetchConfig();
    checkLoginStatus();
    fetchBookInventory();
    fetchSessionInfo();
    fetchLastResults(); // 서버 재기동 시 자동 복원된 이전 세션 결과를 즉시 표시

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
            wakePolling(); // Event-Driven: 클릭 직후 즉시 상태 반영
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
            wakePolling(); // Event-Driven: 클릭 직후 즉시 상태 반영
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

    // Import CSV (기존 작업 복구 — 체크포인트 백필 + Delta 재처리 대상 식별)
    if (btnImportCSV && inputImportCSV) {
        btnImportCSV.addEventListener("click", () => {
            inputImportCSV.value = "";
            inputImportCSV.click();
        });

        inputImportCSV.addEventListener("change", async () => {
            const file = inputImportCSV.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append("file", file);

            try {
                btnImportCSV.disabled = true;
                const res = await fetch("/api/import", {
                    method: "POST",
                    body: formData,
                });
                const data = await res.json();

                if (res.ok) {
                    alert(`${data.message}\n\n(재처리가 필요한 ${data.incomplete}명은 동일한 제출물 폴더로 분석을 다시 시작하면 자동으로 이어서 처리됩니다.)`);
                    await fetchLastResults();
                } else {
                    alert(`CSV 업로드 복구 실패: ${data.detail || "알 수 없는 오류"}`);
                }
            } catch (err) {
                console.error("CSV 업로드 에러:", err);
                alert("CSV 업로드 중 통신 에러가 발생했습니다.");
            } finally {
                btnImportCSV.disabled = false;
            }
        });
    }

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
            // [Workspace Flow] 로그인 직후에는 메인 분석 UI를 바로 열지 않고
            // 프로젝트 대시보드를 먼저 보여준다. 특정 프로젝트가 activate 되었을
            // 때만 enterWorkspace()가 메인 UI를 표시한다.
            if (activeProject) {
                enterWorkspace(activeProject);
            } else {
                showProjectDashboard();
            }
        } else {
            indicator.className = "status-indicator offline";
            statusText.textContent = "로그인 필요";
            btnAuthAction.textContent = "로그인";
            btnAuthAction.className = "btn btn-sm btn-primary";

            mainDashboard.style.display = "none";
            authRequiredPanel.style.display = "block";
            activeProject = null;
            const dash = document.getElementById("projectDashboard");
            const bar = document.getElementById("workspaceBar");
            if (dash) dash.style.display = "none";
            if (bar) bar.style.display = "none";
        }
    }

    // -------------------------------------------------------------
    // 다중 프로젝트(Workspace) 대시보드
    // -------------------------------------------------------------
    function showProjectDashboard() {
        mainDashboard.style.display = "none";
        const bar = document.getElementById("workspaceBar");
        if (bar) bar.style.display = "none";
        const dash = document.getElementById("projectDashboard");
        if (dash) dash.style.display = "block";
        fetchProjects();
    }

    function enterWorkspace(project) {
        activeProject = project;
        const dash = document.getElementById("projectDashboard");
        if (dash) dash.style.display = "none";
        const bar = document.getElementById("workspaceBar");
        if (bar) bar.style.display = "flex";
        const nameEl = document.getElementById("activeProjectName");
        if (nameEl) nameEl.textContent = project.name || project.project_id;
        mainDashboard.style.display = "grid";
        // 활성 프로젝트의 데이터셋/세션 정보/도서 인벤토리를 즉시 렌더링
        fetchLastResults();
        fetchSessionInfo();
        fetchBookInventory();
    }

    async function fetchProjects() {
        const listEl = document.getElementById("projectList");
        if (!listEl) return;
        try {
            const res = await fetch("/api/projects");
            if (!res.ok) {
                const data = await res.json();
                listEl.innerHTML = `<p style="color: var(--text-muted);">${escapeHtml(data.detail || "프로젝트 목록을 불러오지 못했습니다.")}</p>`;
                return;
            }
            const data = await res.json();
            renderProjectList(data.projects || [], data.active_project_id);
        } catch (err) {
            console.error("프로젝트 목록 조회 에러:", err);
        }
    }

    function renderProjectList(projects, activeId) {
        const listEl = document.getElementById("projectList");
        if (!listEl) return;

        if (projects.length === 0) {
            listEl.innerHTML = `
                <div style="text-align: center; padding: 30px 10px; color: var(--text-muted); border: 1px dashed rgba(255,255,255,0.15); border-radius: 8px;">
                    아직 생성된 프로젝트가 없습니다.<br>상단의 <strong>[+ 새 프로젝트 시작하기]</strong> 버튼으로 첫 검토 프로젝트를 만들어 보세요.
                </div>`;
            return;
        }

        listEl.innerHTML = projects.map(p => `
            <div class="card" style="display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 18px; margin: 0;">
                <div style="min-width: 0;">
                    <div style="font-weight: 700; font-size: 14.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        📁 ${escapeHtml(p.name)}
                        ${p.project_id === activeId ? '<span class="badge badge-low" style="margin-left:6px;">활성</span>' : ""}
                        ${p.status === "corrupted" ? '<span class="badge badge-high" style="margin-left:6px;">손상</span>' : ""}
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                        생성: ${escapeHtml(p.created_at || "-")} · 최종 저장: ${escapeHtml(p.saved_at || "-")} · 학생 ${p.student_count}명
                    </div>
                </div>
                <div style="display: flex; gap: 8px; flex-shrink: 0;">
                    <button class="btn btn-sm btn-primary btn-project-resume" data-id="${escapeHtml(p.project_id)}">이어하기</button>
                    <button class="btn btn-sm btn-outline btn-project-delete" data-id="${escapeHtml(p.project_id)}" data-name="${escapeHtml(p.name)}">삭제</button>
                </div>
            </div>
        `).join("");

        listEl.querySelectorAll(".btn-project-resume").forEach(btn => {
            btn.addEventListener("click", () => activateProject(btn.dataset.id));
        });
        listEl.querySelectorAll(".btn-project-delete").forEach(btn => {
            btn.addEventListener("click", () => removeProject(btn.dataset.id, btn.dataset.name));
        });
    }

    async function activateProject(projectId) {
        try {
            const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/activate`, { method: "POST" });
            const data = await res.json();
            if (res.ok) {
                enterWorkspace(data.project);
            } else {
                alert(`프로젝트 활성화 실패: ${data.detail || "알 수 없는 오류"}`);
            }
        } catch (err) {
            console.error("프로젝트 활성화 에러:", err);
        }
    }

    async function createNewProject() {
        const defaultName = `검토 프로젝트 ${new Date().toLocaleDateString("ko-KR")}`;
        const name = prompt("새 프로젝트 이름을 입력하세요:", defaultName);
        if (name === null) return; // 취소
        try {
            const res = await fetch("/api/projects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim() })
            });
            const data = await res.json();
            if (res.ok) {
                await activateProject(data.project.project_id); // 생성 직후 곧바로 작업 공간 진입
            } else {
                alert(`프로젝트 생성 실패: ${data.detail || "알 수 없는 오류"}`);
            }
        } catch (err) {
            console.error("프로젝트 생성 에러:", err);
        }
    }

    async function removeProject(projectId, name) {
        if (!confirm(`'${name}' 프로젝트를 완전히 삭제하시겠습니까?\n(학생 데이터·분석 결과·체크포인트가 모두 삭제되며 되돌릴 수 없습니다)`)) return;
        try {
            const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
            const data = await res.json();
            if (res.ok) {
                if (data.deactivated) activeProject = null;
                await fetchProjects();
            } else {
                alert(`프로젝트 삭제 실패: ${data.detail || "알 수 없는 오류"}`);
            }
        } catch (err) {
            console.error("프로젝트 삭제 에러:", err);
        }
    }

    // [분석 실행] 영역 접기/펼치기 — 좁은 화면에서 하단 정보 확보용
    const btnToggleAnalysisPanel = document.getElementById("btnToggleAnalysisPanel");
    if (btnToggleAnalysisPanel) {
        btnToggleAnalysisPanel.addEventListener("click", () => {
            const body = document.getElementById("analysisPanelBody");
            if (!body) return;
            const isCollapsed = body.style.display === "none";
            body.style.display = isCollapsed ? "" : "none";
            btnToggleAnalysisPanel.textContent = isCollapsed ? "▲ 접기" : "▼ 펼치기";
        });
    }

    const btnCreateProject = document.getElementById("btnCreateProject");
    if (btnCreateProject) {
        btnCreateProject.addEventListener("click", createNewProject);
    }
    const btnBackToProjects = document.getElementById("btnBackToProjects");
    if (btnBackToProjects) {
        btnBackToProjects.addEventListener("click", () => {
            if (["running", "paused", "awaiting_phase", "awaiting_stage3_selection"].includes(lastPipelineStatus)) {
                if (!confirm("분석이 진행/대기 중입니다. 프로젝트 목록으로 나가면 화면 갱신이 중단됩니다 (백그라운드 작업은 계속됨). 나가시겠습니까?")) return;
            }
            showProjectDashboard();
        });
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

        // [Fallback Guard] 구버전 프로필의 단일 모델 스키마({provider, model})가 오더라도
        // 크래시 없이 스크리닝/검증 양쪽 기본값으로 폴백한다.
        const screeningProvider = defaults.screening_provider || defaults.provider || "";
        const screeningModel = defaults.screening_model || defaults.model_screening || defaults.model || "";
        const verifyProvider = defaults.verify_provider || defaults.provider || "";
        const verifyModel = defaults.verify_model || defaults.model_verify || defaults.model || "";

        if (screeningProvider) {
            selectScreeningProvider.value = screeningProvider;
            populateModelDropdown("screening", screeningProvider, selectScreeningModel);
            if (screeningModel) {
                selectScreeningModel.value = screeningModel;
            }
        }

        if (verifyProvider) {
            selectVerifyProvider.value = verifyProvider;
            populateModelDropdown("verify", verifyProvider, selectVerifyModel);
            if (verifyModel) {
                selectVerifyModel.value = verifyModel;
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
    // Data Ingestion (파일 읽기 — 분석 파이프라인과 완전 분리, Smart Append)
    // -------------------------------------------------------------
    const btnImportData = document.getElementById("btnImportData");
    if (btnImportData) {
        btnImportData.addEventListener("click", async () => {
            const path = submissionsDir.value && submissionsDir.value.trim ? submissionsDir.value.trim() : submissionsDir.value;
            if (!path) {
                alert("먼저 가져올 제출물 파일을 선택해 주세요.");
                return;
            }
            try {
                btnImportData.disabled = true;
                btnImportData.textContent = "가져오는 중...";
                const res = await fetch("/api/data/import", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path })
                });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message);
                    await fetchLastResults();   // 메모리 데이터셋(추가분 포함)을 목록에 즉시 반영
                    await fetchSessionInfo();   // session_progress.json 동기화 정보 갱신
                } else {
                    alert(`데이터 가져오기 실패: ${data.detail || "알 수 없는 오류"}`);
                }
            } catch (err) {
                console.error("데이터 가져오기 API 에러:", err);
                alert("데이터 가져오기 중 통신 에러가 발생했습니다.");
            } finally {
                btnImportData.disabled = false;
                btnImportData.textContent = "📥 데이터 가져오기 (중복 자동 병합)";
            }
        });
    }

    // -------------------------------------------------------------
    // Analysis Logic — 파이프라인은 폴더를 읽지 않고 메모리 데이터셋만 순회한다
    // -------------------------------------------------------------
    async function startAnalysis() {
        const payload = {
            verify_all: verifyAll.checked,
            no_verify: noVerify.checked,
            no_web: noWeb.checked,

            screening_provider: selectScreeningProvider.value,
            screening_model: selectScreeningModel.value,
            verify_provider: selectVerifyProvider.value,
            verify_model: selectVerifyModel.value
        };

        if (!currentResults || currentResults.length === 0) {
            alert("적재된 학생 데이터가 없습니다. 먼저 [데이터 가져오기] 또는 [학생 수동 추가]로 학생을 등록해 주세요.");
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

                // 즉시 1회 호출 — 이후에는 pollProgress가 파이프라인 상태에 따라
                // 스스로 다음 폴링을 예약한다 (활성 작업 2초 / 대기 keep-alive 60초 / 종료 시 파괴).
                wakePolling();
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

        // 좌측 사이드바로 이동된 파이프라인 제어 버튼: 파이프라인이 실제로
        // 살아있는 상태(진행/일시정지/단계 대기)에서만 활성화한다.
        const pipelineAlive = ["running", "paused", "awaiting_phase", "awaiting_stage3_selection"].includes(stateName);
        if (btnPauseFrame) btnPauseFrame.disabled = !pipelineAlive;
        if (btnStopFrame) btnStopFrame.disabled = !pipelineAlive;

        if (stateName === "idle" || stateName === "completed" || stateName === "stopped") {
            // 대기/완료 상태: 대기 화면 활성화
            frameStateIdle.style.display = "block";
            
            // 왼쪽 분석 실행 버튼 활성화
            if (btnStartAnalyze) btnStartAnalyze.disabled = false;
        } else if (stateName === "running" || stateName === "paused" || stateName === "awaiting_phase" || stateName === "awaiting_stage3_selection") {
            // 작업 진행 중 상태(단계 게이트/3단계 대상 선택 대기 포함): 진행 화면 활성화
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

    // -------------------------------------------------------------
    // [Zero-Idle Polling] 상태 적응형 폴링 스케줄러
    // - 활성 작업(파이프라인 running/paused, 팩트시트 생성 중)일 때만 2초 주기.
    // - 대기 상태(awaiting_phase / awaiting_stage3_selection)에서는 60초 keep-alive만
    //   유지하며, 이때 호출하는 /api/analyze/status는 서버 인메모리 스냅샷 반환뿐
    //   (파일 읽기 등 서버 I/O 0). 상태 전환은 사용자 버튼 클릭(wakePolling)이
    //   즉시 반영하므로 대기 중 잦은 폴링이 필요 없다 (Event-Driven).
    // - 파이프라인 종료(completed/error/stopped/idle) 시 타이머를 즉시 파괴한다.
    // -------------------------------------------------------------
    const POLL_FAST_MS = 2000;
    const POLL_KEEPALIVE_MS = 60000;

    function stopPolling() {
        if (pollTimer) {
            clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function schedulePoll(delayMs) {
        stopPolling();
        pollTimer = setTimeout(pollProgress, delayMs);
    }

    // 사용자 클릭 등 명시적 이벤트 직후 즉시 1회 상태를 갱신한다.
    // (keep-alive 60초를 기다리지 않고 UI가 곧바로 반응하도록 하는 Event-Driven 훅)
    function wakePolling() {
        stopPolling();
        pollProgress();
    }

    async function pollProgress() {
        let nextDelay = null; // null이면 폴링 종료 (타이머 파괴 상태 유지)
        try {
            const res = await fetch("/api/analyze/status");
            const state = await res.json();

            // 백엔드 상태에 따른 중앙 프레임 조건부 전환
            switchFrameState(state.status);
            lastPipelineStatus = state.status;

            // 활성 작업 판정: LLM/무거운 연산이 실제로 돌고 있는 상태에서만 빠른 폴링 유지
            const isActiveWork = state.status === "running" || state.status === "paused";
            const generatingNow = Boolean(state.factsheet_generating);
            const isWaitingGate = state.status === "awaiting_phase" || state.status === "awaiting_stage3_selection";

            // 3단계 대상 선택 대기 상태: 듀얼 패널 모달 초기화 및 1회 자동 오픈
            if (state.status === "awaiting_stage3_selection" && state.stage3_selection) {
                if (!stage3ModalAutoOpened) {
                    initStage3Selection(state.stage3_selection);
                    openStage3Modal();
                    stage3ModalAutoOpened = true;
                }
            } else {
                stage3ModalAutoOpened = false;
                if (modalStage3Select && modalStage3Select.style.display !== "none" && state.status !== "awaiting_stage3_selection") {
                    modalStage3Select.style.display = "none"; // 확정/종료 후 잔여 모달 정리
                }
            }

            if (state.status === "running" || state.status === "paused" || state.status === "awaiting_phase" || state.status === "awaiting_stage3_selection") {
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

                // [JIT 팩트시트 스피너] Cache Miss로 도서 1권을 신규 생성 중이면
                // "'{도서명}' 팩트시트 신규 생성 중..." 배너를 표시하여 시스템이
                // 다운된 것이 아님을 사용자에게 인지시킨다 (백엔드 factsheet_generating 플래그 연동).
                const factsheetGenBanner = document.getElementById("factsheetGenBanner");
                const factsheetGenText = document.getElementById("factsheetGenText");
                if (factsheetGenBanner && factsheetGenText) {
                    if (state.factsheet_generating) {
                        factsheetGenText.textContent = `'${state.factsheet_generating}' 팩트시트 신규 생성 중... (LLM 호출 — 시스템이 멈춘 것이 아닙니다)`;
                        factsheetGenBanner.style.display = "flex";
                    } else {
                        factsheetGenBanner.style.display = "none";
                    }
                }

                // [Guard — Zero-Idle Polling] 서버 부하가 있는 부가 조회는 '활성 작업 중'에만 수행:
                // - /api/results (인메모리): 학생 처리 결과가 실제로 갱신되는 동안만 재조회.
                // - /api/book-inventory (book_cache.json 파일 재파싱): 주기 타이머를 완전히 제거하고,
                //   팩트시트 생성이 '활성 → 비활성'으로 전환되는 순간에만 1회 갱신(Event-Driven).
                // 대기 상태(awaiting_*)의 60초 keep-alive 턴에서는 이 블록이 전부 생략되어
                // /api/analyze/status(메모리 스냅샷) 단일 호출 외 어떤 서버 I/O도 발생하지 않는다.
                if (isActiveWork || generatingNow) {
                    await refreshLiveResults();
                }
                if (lastGeneratingActive && !generatingNow) {
                    await fetchBookInventory(); // 생성 종료 시점 1회 (신규 팩트시트 반영)
                }
                lastGeneratingActive = generatingNow;
            }

            // Task 5: 단계 게이트/3단계 대상 선택 대기 상태에서만 게이팅 버튼 활성화
            if (btnNextPhase) {
                btnNextPhase.disabled = state.status !== "awaiting_phase" && state.status !== "awaiting_stage3_selection";
                if (btnNextPhaseText) {
                    if (state.status === "awaiting_phase" && state.awaiting_phase === "phase2") {
                        btnNextPhaseText.textContent = "2단계(AI 스크리닝) 진행";
                    } else if (state.status === "awaiting_stage3_selection") {
                        btnNextPhaseText.textContent = "3단계 검증 대상 선택하기";
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
                stopPolling();
                btnStartAnalyze.disabled = false;
                switchFrameState("idle");
                await fetchLastResults();
                await fetchBookInventory();
                await fetchSessionInfo(); // 완료 시점의 세션 스냅샷 저장 정보 갱신
                alert("선별 분석 작업이 완료되었습니다!");
            } else if (state.status === "error") {
                stopPolling();
                btnStartAnalyze.disabled = false;
                
                // [에러 발생 상태] 전환 및 메시지 설정
                const frameErrorMessage = document.getElementById("frameErrorMessage");
                if (frameErrorMessage) {
                    frameErrorMessage.textContent = state.error_message || "분석 수행 도중 심각한 에러가 발생했습니다.";
                }
                switchFrameState("error");
            } else if (state.status === "stopped") {
                stopPolling();
                btnStartAnalyze.disabled = false;
                switchFrameState("idle");
                alert("분석 작업이 강제 종료되었습니다.");
            }

            // [Zero-Idle Polling 스케줄러] 이번 턴의 상태를 기준으로 다음 폴링을 결정한다.
            // 종료 상태면 nextDelay=null 그대로 두어 타이머를 완전히 파괴한다.
            if (isActiveWork || generatingNow) {
                nextDelay = POLL_FAST_MS;       // 실제 작업/생성 중에만 빠른 갱신
            } else if (isWaitingGate) {
                nextDelay = POLL_KEEPALIVE_MS;  // 대기 상태: 60초 메모리 핑 keep-alive만
            }

        } catch (err) {
            console.error("상태 폴링 오류:", err);
            // 통신 실패 시에도 빠른 재시도로 서버를 두드리지 않고 keep-alive 주기로만 재시도
            nextDelay = POLL_KEEPALIVE_MS;
        }

        if (nextDelay !== null) {
            schedulePoll(nextDelay);
        } else {
            stopPolling();
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

    // 메인 결과 테이블과 [로컬 도서 인벤토리] 패널이 공유하는 "팩트시트 보강" 트리거.
    // 두 위치의 버튼 모두 동일한 /api/analyze/enrich-factsheet 엔드포인트를 호출한다.
    async function triggerEnrichFactsheet(btn, bookTitle, author) {
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
                // 인벤토리 패널이 열려 있다면 갱신된 팩트시트 메타데이터를 즉시 반영
                await fetchBookInventory();
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
                    <div class="action-btn-group">
                        <button class="btn btn-sm btn-outline btn-view-factsheet" data-cache-key="${escapeHtml(b.cache_key)}" data-title="${escapeHtml(b.book_title || "")}">
                            팩트시트 확인
                        </button>
                        <button class="btn btn-sm btn-success btn-enrich-factsheet-inv" data-title="${escapeHtml(b.book_title || "")}" data-author="${escapeHtml(b.author || "")}">
                            팩트시트 보강
                        </button>
                    </div>
                </td>
            </tr>
        `).join("");

        document.querySelectorAll(".btn-view-factsheet").forEach(btn => {
            btn.addEventListener("click", () => {
                openFactsheetView(btn.dataset.cacheKey, btn.dataset.title);
            });
        });

        // Task(인벤토리): 메인 결과 테이블의 "팩트시트 보강"과 완전히 동일한 API를 호출한다.
        document.querySelectorAll(".btn-enrich-factsheet-inv").forEach(btn => {
            btn.addEventListener("click", () => {
                triggerEnrichFactsheet(btn, btn.dataset.title, btn.dataset.author);
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

    // Task 5: [다음 단계 진행] 버튼 — 단계 경계 게이트를 해제한다.
    // 단, 3단계 대상 선택 대기 상태에서는 즉시 진행하지 않고 듀얼 패널 모달을 연다.
    if (btnNextPhase) {
        btnNextPhase.addEventListener("click", async () => {
            if (lastPipelineStatus === "awaiting_stage3_selection") {
                openStage3Modal();
                return;
            }
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
            wakePolling(); // Event-Driven: 클릭 직후 즉시 상태 반영 (keep-alive 60초를 기다리지 않음)
        });
    }

    // -------------------------------------------------------------
    // 3단계 심층 검증 대상 선택 모달 (듀얼 패널 Transfer List)
    // -------------------------------------------------------------
    function initStage3Selection(selectionPayload) {
        stage3Candidates = selectionPayload.candidates || [];
        // Auto-selection: 1·2단계 임계치 초과 위험군이 미리 체크된 상태로 초기화
        stage3SelectedSet = new Set(selectionPayload.preselected || []);
        renderStage3Panels();
    }

    function openStage3Modal() {
        if (!modalStage3Select) return;
        renderStage3Panels();
        modalStage3Select.style.display = "flex";
    }

    // 1단계 위험도 등급(Safe/Warning/Danger) 배지 HTML 생성 (결과 테이블·모달 공용)
    function stage1GradeBadge(record) {
        const score = parseFloat(record.rule_score);
        if (isNaN(score)) return "";
        let grade = record.risk_grade;
        if (!grade) {
            // 하위 호환: 구버전 결과(risk_grade 없음)는 프론트에서 동일 임계값으로 산출
            grade = score >= 45 ? "Danger" : (score >= 20 ? "Warning" : "Safe");
        }
        const map = {
            "Safe": ["grade-safe", "🟢 Safe"],
            "Warning": ["grade-warning", "🟡 Warning"],
            "Danger": ["grade-danger", "🔴 Danger"]
        };
        const [cls, label] = map[grade] || map["Safe"];
        return `<span class="badge ${cls}">${label}</span>`;
    }

    // 듀얼 패널 리스트 아이템: 이전 단계 판단 결과 요약을 뱃지로 함께 렌더링
    function stage3ItemHtml(c, isSelected) {
        const tierBadge = c.tier
            ? `<span class="badge ${c.tier === "최우선" ? "badge-top-priority" : c.tier === "상" ? "badge-high" : c.tier === "중" ? "badge-medium" : "badge-low"}">${escapeHtml(c.tier)}</span>`
            : "";
        const signalsText = (c.signals && c.signals.length > 0)
            ? `<span class="ti-signals" title="${escapeHtml(c.signals.join(" / "))}">⚠ ${escapeHtml(c.signals[0])}${c.signals.length > 1 ? ` 외 ${c.signals.length - 1}건` : ""}</span>`
            : `<span class="ti-signals ti-signals-none">감지 신호 없음</span>`;

        return `
            <li class="transfer-item ${isSelected ? "transfer-item-selected" : ""}" data-student="${escapeHtml(c.student)}" title="클릭하면 ${isSelected ? "대기 명단으로 제외" : "검증 대상으로 추가"}됩니다">
                <div class="ti-main">
                    <span class="ti-name">${escapeHtml(c.student_name || c.student)}</span>
                    <span class="ti-book">${escapeHtml(c.book_title || "도서 미상")}</span>
                </div>
                <div class="ti-badges">
                    ${stage1GradeBadge(c)}
                    <span class="ti-score">1단계 ${c.rule_score ?? "-"}점</span>
                    <span class="ti-score">2단계 ${c.ai_score ?? "-"}점</span>
                    ${tierBadge}
                </div>
                ${signalsText}
                <span class="ti-toggle-icon">${isSelected ? "✕" : "＋"}</span>
            </li>
        `;
    }

    function renderStage3Panels() {
        if (!stage3LeftList || !stage3RightList) return;

        const leftItems = stage3Candidates.filter(c => !stage3SelectedSet.has(c.student));
        const rightItems = stage3Candidates.filter(c => stage3SelectedSet.has(c.student));

        stage3LeftList.innerHTML = leftItems.length > 0
            ? leftItems.map(c => stage3ItemHtml(c, false)).join("")
            : `<li class="transfer-empty">대기 중인 학생이 없습니다.</li>`;
        stage3RightList.innerHTML = rightItems.length > 0
            ? rightItems.map(c => stage3ItemHtml(c, true)).join("")
            : `<li class="transfer-empty">아직 선택된 학생이 없습니다.<br>좌측 명단에서 클릭하여 추가하세요.</li>`;

        stage3LeftCount.textContent = leftItems.length;
        stage3RightCount.textContent = rightItems.length;
        if (stage3SelectSummary) {
            stage3SelectSummary.textContent =
                `선택 ${rightItems.length}명 / 전체 ${stage3Candidates.length}명 — 선택된 학생만 Batch로 LLM에 전송됩니다.`;
        }

        // 원클릭 토글(Click-to-Toggle): 아이템 클릭만으로 패널 간 즉시 이동
        modalStage3Select.querySelectorAll(".transfer-item").forEach(li => {
            li.addEventListener("click", () => {
                const key = li.dataset.student;
                if (stage3SelectedSet.has(key)) {
                    stage3SelectedSet.delete(key);
                } else {
                    stage3SelectedSet.add(key);
                }
                renderStage3Panels();
            });
        });
    }

    if (btnStage3SelectAll) {
        btnStage3SelectAll.addEventListener("click", () => {
            stage3Candidates.forEach(c => stage3SelectedSet.add(c.student));
            renderStage3Panels();
        });
    }
    if (btnStage3ClearAll) {
        btnStage3ClearAll.addEventListener("click", () => {
            stage3SelectedSet.clear();
            renderStage3Panels();
        });
    }
    if (btnCloseStage3Modal) {
        // 닫기는 '보류'일 뿐 — 파이프라인은 선택 확정까지 계속 대기(토큰 소모 0)하며,
        // [3단계 검증 대상 선택하기] 버튼으로 언제든 다시 열 수 있다.
        btnCloseStage3Modal.addEventListener("click", () => {
            modalStage3Select.style.display = "none";
        });
    }

    // 최종 실행 훅(Execution Hook): 이 버튼을 눌러야만 우측 패널의 학생들이
    // Batch 배열로 묶여 LLM으로 전송된다.
    async function submitStage3Selection(selectedKeys) {
        try {
            btnStage3Confirm.disabled = true;
            btnStage3Skip.disabled = true;
            const res = await fetch("/api/analyze/stage3-selection", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ students: selectedKeys })
            });
            if (res.ok) {
                modalStage3Select.style.display = "none";
                wakePolling(); // Event-Driven: 확정 직후 즉시 3단계 진행 상태(2초 폴링)로 전환
            } else {
                const errData = await res.json();
                alert(`검증 대상 확정 실패: ${errData.detail || "알 수 없는 오류"}`);
            }
        } catch (err) {
            console.error("3단계 대상 확정 API 에러:", err);
            alert("검증 대상 확정 중 통신 에러가 발생했습니다.");
        } finally {
            btnStage3Confirm.disabled = false;
            btnStage3Skip.disabled = false;
        }
    }

    if (btnStage3Confirm) {
        btnStage3Confirm.addEventListener("click", async () => {
            const selected = stage3Candidates
                .filter(c => stage3SelectedSet.has(c.student))
                .map(c => c.student);
            if (selected.length === 0) {
                if (!confirm("선택된 학생이 없습니다. 3단계 검증을 건너뛰시겠습니까? (토큰 소모 0)")) return;
            }
            await submitStage3Selection(selected);
        });
    }
    if (btnStage3Skip) {
        btnStage3Skip.addEventListener("click", async () => {
            if (!confirm("3단계 심층 검증을 완전히 생략하시겠습니까? (선택된 학생이 있어도 검증하지 않습니다)")) return;
            await submitStage3Selection([]);
        });
    }

    // -------------------------------------------------------------
    // 세션 진행 상태 파일 UI (State Portability — 작업 이어하기/공유)
    // -------------------------------------------------------------
    async function fetchSessionInfo() {
        try {
            const res = await fetch("/api/session/info");
            if (!res.ok) return;
            const info = await res.json();
            if (sessionFileName) sessionFileName.textContent = info.filename || "session_progress.json";
            if (sessionFilePath) {
                const savedStr = info.exists
                    ? `최종 저장 ${info.saved_at || "미상"} · ${info.student_count}명`
                    : "저장 이력 없음 (분석 시작 시 자동 생성)";
                sessionFilePath.textContent = `${info.path} — ${savedStr}`;
                sessionFilePath.title = info.path;
            }
            if (btnDownloadSession) btnDownloadSession.disabled = !info.exists;
        } catch (err) {
            console.error("세션 파일 정보 조회 에러:", err);
        }
    }

    if (btnDownloadSession) {
        btnDownloadSession.addEventListener("click", () => {
            window.location.href = "/api/session/download";
        });
    }
    if (btnUploadSession && inputUploadSession) {
        btnUploadSession.addEventListener("click", () => inputUploadSession.click());
        inputUploadSession.addEventListener("change", async () => {
            const file = inputUploadSession.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append("file", file);
            try {
                btnUploadSession.disabled = true;
                const res = await fetch("/api/session/upload", { method: "POST", body: formData });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message || "세션 복원 완료");
                    await fetchLastResults();
                    await fetchSessionInfo();
                } else {
                    alert(`세션 복원 실패: ${data.detail || "알 수 없는 오류"}`);
                }
            } catch (err) {
                console.error("세션 업로드 에러:", err);
                alert("세션 파일 업로드 중 통신 에러가 발생했습니다.");
            } finally {
                btnUploadSession.disabled = false;
                inputUploadSession.value = "";
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

    // -------------------------------------------------------------
    // 학생 수동 추가 / 수정 모달 (CRUD)
    // -------------------------------------------------------------
    const modalStudentForm = document.getElementById("modalStudentForm");
    const studentFormTitle = document.getElementById("studentFormTitle");
    const sfOriginalKey = document.getElementById("sfOriginalKey");
    const sfStudentId = document.getElementById("sfStudentId");
    const sfStudentName = document.getElementById("sfStudentName");
    const sfBookTitle = document.getElementById("sfBookTitle");
    const sfText = document.getElementById("sfText");

    function openStudentForm(mode, record) {
        if (!modalStudentForm) return;
        const isEdit = mode === "edit" && record;
        sfOriginalKey.value = isEdit ? record.student : "";
        studentFormTitle.textContent = isEdit ? `✏️ 학생 정보 수정: ${record.student}` : "👤 학생 수동 추가";
        sfStudentId.value = isEdit ? (record.student_id || "") : "";
        sfStudentName.value = isEdit ? (record.student_name || "") : "";
        sfBookTitle.value = isEdit ? (record.book_title || "") : "";
        sfText.value = isEdit ? (record.text || "") : "";
        modalStudentForm.style.display = "flex";
    }

    function closeStudentForm() {
        if (modalStudentForm) modalStudentForm.style.display = "none";
    }

    async function submitStudentForm() {
        const originalKey = sfOriginalKey.value;
        const body = {
            student_id: sfStudentId.value.trim(),
            student_name: sfStudentName.value.trim(),
            book_title: sfBookTitle.value.trim(),
            text: sfText.value.trim()
        };
        if (!body.student_name) {
            alert("이름은 필수 입력입니다.");
            return;
        }
        if (!originalKey && !body.text) {
            alert("독후감 본문을 입력(붙여넣기)해 주세요.");
            return;
        }

        const url = originalKey ? `/api/students/${encodeURIComponent(originalKey)}` : "/api/students";
        const method = originalKey ? "PUT" : "POST";
        try {
            const res = await fetch(url, {
                method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (res.ok) {
                closeStudentForm();
                await fetchLastResults();  // 메모리 데이터셋 변경분 즉시 반영
                await fetchSessionInfo();  // 세션 파일 저장 정보 갱신
            } else {
                alert(`저장 실패: ${data.detail || "알 수 없는 오류"}`);
            }
        } catch (err) {
            console.error("학생 저장 API 에러:", err);
            alert("저장 중 통신 에러가 발생했습니다.");
        }
    }

    const btnAddStudent = document.getElementById("btnAddStudent");
    if (btnAddStudent) {
        btnAddStudent.addEventListener("click", () => openStudentForm("add", null));
    }
    const btnSubmitStudentForm = document.getElementById("btnSubmitStudentForm");
    if (btnSubmitStudentForm) {
        btnSubmitStudentForm.addEventListener("click", submitStudentForm);
    }
    const btnCancelStudentForm = document.getElementById("btnCancelStudentForm");
    if (btnCancelStudentForm) {
        btnCancelStudentForm.addEventListener("click", closeStudentForm);
    }
    const btnCloseStudentForm = document.getElementById("btnCloseStudentForm");
    if (btnCloseStudentForm) {
        btnCloseStudentForm.addEventListener("click", closeStudentForm);
    }

    // -------------------------------------------------------------
    // 테이블 정렬 (th 클릭 → 오름차순/내림차순 토글, 🔼/🔽 인디케이터)
    // -------------------------------------------------------------
    let sortState = { key: null, dir: 1 }; // dir: 1=ASC, -1=DESC
    const SORT_NUMERIC_KEYS = new Set(["rule_score", "ai_score", "hallucination_score"]);
    const TIER_SORT_ORDER = { "최우선": 3, "상": 2, "중": 1, "하": 0 };

    function sortValue(r, key) {
        if (key === "tier") {
            return TIER_SORT_ORDER[r.tier] !== undefined ? TIER_SORT_ORDER[r.tier] : -1;
        }
        const v = r[key];
        if (SORT_NUMERIC_KEYS.has(key)) {
            const n = parseFloat(v);
            return isNaN(n) ? -Infinity : n; // 미실시/대기중은 항상 최하단(ASC 기준 최상단) 그룹
        }
        return (v === null || v === undefined) ? "" : String(v);
    }

    function updateSortIndicators() {
        document.querySelectorAll("#resultsTable th.sortable").forEach(th => {
            if (!th.dataset.label) th.dataset.label = th.textContent.trim();
            th.textContent = th.dataset.sort === sortState.key
                ? `${th.dataset.label} ${sortState.dir === 1 ? "🔼" : "🔽"}`
                : th.dataset.label;
        });
    }

    document.querySelectorAll("#resultsTable th.sortable").forEach(th => {
        th.addEventListener("click", () => {
            const key = th.dataset.sort;
            if (sortState.key === key) {
                sortState.dir = -sortState.dir; // 같은 컬럼 재클릭 → ASC/DESC 토글
            } else {
                sortState = { key, dir: 1 };
            }
            updateSortIndicators();
            renderResultsTable(currentResults);
        });
    });

    function renderResultsTable(results) {
        const tier = filterTier.value;
        let filtered = results;

        if (tier !== "all") {
            filtered = results.filter(r => r.tier === tier);
        }

        // 정렬 적용 (원본 배열은 건드리지 않고 사본으로 정렬)
        if (sortState.key) {
            filtered = [...filtered].sort((a, b) => {
                const va = sortValue(a, sortState.key);
                const vb = sortValue(b, sortState.key);
                const cmp = (typeof va === "number" && typeof vb === "number")
                    ? va - vb
                    : String(va).localeCompare(String(vb), "ko");
                return cmp * sortState.dir;
            });
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

            // 1단계 결과: 점수 + 위험도 등급 배지 (Safe/Warning/Danger — 토큰 비소비 로컬 판정)
            const stage1Str = r.rule_score !== undefined
                ? `${r.rule_score}점 ${stage1GradeBadge(r)}`
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
                    <td class="cell-ellipsis" title="${escapeHtml(r.book_title || "미상")}">${escapeHtml(r.book_title || "미상")}</td>
                    <td>${stage1Str}</td>
                    <td>${stage2Str}</td>
                    <td>${stage3Str}</td>
                    <td><span class="badge ${badgeClass}">${r.tier || "-"}</span></td>
                    <td>
                        <!-- 가로 1줄 강제(.action-btn-group): 세로 누적으로 행 높이가 팽창하는 결함 방지 -->
                        <div class="action-btn-group">
                            <button class="btn btn-sm btn-outline btn-view-detail" data-student="${escapeHtml(r.student)}">
                                상세보기
                            </button>
                            <button class="btn btn-sm btn-success btn-enrich-factsheet" data-title="${escapeHtml(r.book_title || '')}" data-author="${escapeHtml(r.author || r.stage2?.author || '')}">
                                팩트시트 보강
                            </button>
                            <button class="btn btn-sm btn-outline btn-edit-student" data-student="${escapeHtml(r.student)}" title="학생 정보 수정">✏️</button>
                            <button class="btn btn-sm btn-outline btn-delete-student" data-student="${escapeHtml(r.student)}" title="학생 삭제">🗑️</button>
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

        // [CRUD] 행 단위 수정/삭제 액션
        document.querySelectorAll(".btn-edit-student").forEach(btn => {
            btn.addEventListener("click", () => {
                const record = currentResults.find(r => r.student === btn.dataset.student);
                if (!record) {
                    alert("해당 학생 데이터를 찾을 수 없습니다.");
                    return;
                }
                openStudentForm("edit", record);
            });
        });

        document.querySelectorAll(".btn-delete-student").forEach(btn => {
            btn.addEventListener("click", async () => {
                const key = btn.dataset.student;
                if (!confirm(`'${key}' 학생을 목록과 세션 파일에서 완전히 삭제하시겠습니까?\n(분석 결과 포함, 되돌릴 수 없습니다)`)) return;
                try {
                    const res = await fetch(`/api/students/${encodeURIComponent(key)}`, { method: "DELETE" });
                    const data = await res.json();
                    if (res.ok) {
                        await fetchLastResults();
                        await fetchSessionInfo();
                    } else {
                        alert(`삭제 실패: ${data.detail || "알 수 없는 오류"}`);
                    }
                } catch (err) {
                    console.error("학생 삭제 API 에러:", err);
                    alert("삭제 중 통신 에러가 발생했습니다.");
                }
            });
        });

        document.querySelectorAll(".btn-enrich-factsheet").forEach(btn => {
            btn.addEventListener("click", () => {
                triggerEnrichFactsheet(btn, btn.dataset.title, btn.dataset.author);
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
