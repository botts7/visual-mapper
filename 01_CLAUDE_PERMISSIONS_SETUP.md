# Claude Permissions Setup - Autonomous Development

**Purpose:** Configure Claude Code to test Visual Mapper autonomously without requiring user approval for every command.

**Starting Version:** 0.0.1
**Last Updated:** 2025-12-21

---

## ⚠️ IMPORTANT: This is for USER to configure!

**This document is for YOU (the user) to implement, NOT for Claude to execute.**

Claude cannot configure these permissions autonomously. You must manually set up these files on your system to enable Claude to work more efficiently.

---

## 🎯 Goal

Enable Claude to:
- ✅ Run tests on localhost:3000 automatically
- ✅ Execute read-only bash commands without approval
- ✅ Access Docker development environment
- ✅ Run Playwright/Jest tests autonomously
- ✅ Read all project files
- ❌ Push to git (requires user approval)
- ❌ Modify production files without tests passing

---

## 📋 Prerequisites

Before configuring permissions, ensure you have:

1. **Claude Code installed** (latest version)
2. **VS Code** with Remote Containers extension
3. **Docker Desktop** running
4. **Git** configured with user credentials
5. **Home Assistant** (optional - for final validation)

---

## 🔧 Configuration Methods

Claude Code supports two permission configuration methods:

### **Method 1: ~/.claude.json (Recommended)**
- Global configuration across all projects
- Most consistent behavior
- Best for autonomous development

### **Method 2: Project-specific .claude/config.json**
- Per-project configuration
- Overrides global settings
- Good for project-specific tools

**We recommend Method 1 for Visual Mapper**

---

## 📝 Step 1: Create ~/.claude.json

### **Location:**
- **Windows:** `C:\Users\<USERNAME>\.claude.json`
- **macOS/Linux:** `~/.claude.json`

### **Full Configuration:**

```json
{
  "mcpServers": {},
  "permissions": {
    "visual_mapper": {
      "allowedCommands": [
        "ls",
        "cat",
        "pwd",
        "dir",
        "git status",
        "git diff",
        "git log",
        "git branch",
        "git checkout",
        "npm test",
        "npm run test:unit",
        "npm run test:e2e",
        "pytest",
        "playwright test",
        "docker ps",
        "docker logs",
        "docker exec",
        "curl localhost:3000/*",
        "curl localhost:8099/*",
        "curl localhost:8100/*"
      ],
      "allowedDirectories": [
        "C:\\Users\\botts\\Downloads\\Visual Mapper",
        "C:\\Users\\botts\\Downloads\\Visual Mapper\\www",
        "C:\\Users\\botts\\Downloads\\Visual Mapper\\tests",
        "C:\\Users\\botts\\Downloads\\Visual Mapper\\docs"
      ],
      "requireConfirmation": {
        "commands": [
          "git push",
          "git commit",
          "git merge",
          "docker build",
          "docker-compose up",
          "rm -rf",
          "del /S /Q"
        ],
        "directories": [
          "C:\\Users\\botts\\Downloads\\Visual Mapper\\.git",
          "C:\\Users\\botts\\Downloads\\Visual Mapper\\config.yaml",
          "C:\\Users\\botts\\Downloads\\Visual Mapper\\Dockerfile"
        ]
      },
      "blockedCommands": [
        "format C:",
        "rm -rf /",
        "sudo rm",
        "git push --force origin master",
        "git push --force origin develop",
        "docker system prune -a"
      ]
    }
  }
}
```

---

## 📖 Configuration Explained

### **allowedCommands**

These commands run **without user confirmation**:

#### **File Operations**
```bash
ls                    # List directory contents
cat <file>            # Read file contents
pwd                   # Print working directory
dir                   # Windows directory list
```

#### **Git Read-Only**
```bash
git status            # Check git status
git diff              # View changes
git log               # View commit history
git branch            # List branches
git checkout <branch> # Switch branches (read-only operation)
```

#### **Testing**
```bash
npm test              # Run all tests
npm run test:unit     # Run unit tests only
npm run test:e2e      # Run E2E tests only
pytest                # Python tests
playwright test       # Playwright E2E tests
```

#### **Docker Read-Only**
```bash
docker ps             # List containers
docker logs <id>      # View container logs
docker exec <id> <cmd> # Execute command in container
```

#### **Local API Access**
```bash
curl localhost:3000/* # Frontend testing
curl localhost:8099/* # Backend API testing
curl localhost:8100/* # Stream server testing
```

### **allowedDirectories**

Claude can read/write files in these directories **without confirmation**:

```
C:\Users\botts\Downloads\Visual Mapper       # Project root
C:\Users\botts\Downloads\Visual Mapper\www   # Frontend files
C:\Users\botts\Downloads\Visual Mapper\tests # Test files
C:\Users\botts\Downloads\Visual Mapper\docs  # Documentation
```

**Note:** Adjust paths based on your actual project location.

### **requireConfirmation**

These commands **require user approval** before execution:

#### **Git Write Operations**
```bash
git push              # Push to remote
git commit            # Create commit
git merge             # Merge branches
```

**Why:** Prevents accidental pushes to production

#### **Docker Build Operations**
```bash
docker build          # Build image
docker-compose up     # Start services
```

**Why:** These can consume significant resources

#### **Dangerous File Operations**
```bash
rm -rf                # Recursive delete (Linux/Mac)
del /S /Q             # Recursive delete (Windows)
```

**Why:** Prevents accidental data loss

#### **Critical Files**
```
.git/                 # Git metadata
config.yaml           # HA addon configuration
Dockerfile            # Container build file
```

**Why:** Changes can break deployment

### **blockedCommands**

These commands are **completely blocked**:

```bash
format C:                          # Format drive (Windows)
rm -rf /                           # Delete root (Linux/Mac)
sudo rm                            # Elevated delete
git push --force origin master     # Force push to master
git push --force origin develop    # Force push to develop
docker system prune -a             # Delete all Docker data
```

**Why:** These can cause catastrophic data loss or break production

---

## 🚀 Step 2: Create Project-Specific Config (Optional)

If you need project-specific tools, create `.claude/config.json` in project root:

```json
{
  "tools": {
    "visual_mapper_test_server": {
      "command": "npm run dev",
      "description": "Start development server on port 3000",
      "autoApprove": true
    },
    "run_playwright_tests": {
      "command": "playwright test --headed",
      "description": "Run Playwright tests with browser visible",
      "autoApprove": true
    },
    "check_api_health": {
      "command": "curl http://localhost:8099/api/adb/devices",
      "description": "Check if API server is responding",
      "autoApprove": true
    }
  }
}
```

---

## 🔐 Security Best Practices

### **Principle of Least Privilege**

Start with **deny-all** and allowlist only what's needed:

```json
{
  "permissions": {
    "visual_mapper": {
      "defaultDeny": true,
      "allowedCommands": [
        /* Only add what you need */
      ]
    }
  }
}
```

### **Directory Sandboxing**

Limit file access to project directories:

```json
{
  "allowedDirectories": [
    "C:\\Users\\botts\\Downloads\\Visual Mapper"  // Project only
  ]
}
```

**Don't allow:**
- `C:\` or `/` (entire system)
- User home directory
- System directories

### **Command Validation**

Always validate commands before adding to allowlist:

```bash
# ✅ Safe - read-only
git status
docker ps

# ⚠️ Requires confirmation - write operation
git push
docker build

# ❌ Blocked - dangerous
rm -rf /
format C:
```

---

## 🧪 Step 3: Test Configuration

### **Test 1: Read-Only Commands (Should Auto-Approve)**

Open Claude Code and test these commands should run **without asking**:

```bash
# File operations
ls
cat README.md
pwd

# Git read-only
git status
git log --oneline -5

# Docker read-only
docker ps
```

**Expected:** Commands execute immediately, no confirmation prompt

### **Test 2: Write Commands (Should Ask Confirmation)**

Test these commands should **ask for approval**:

```bash
# Git write
git commit -m "test"

# Docker build
docker build .
```

**Expected:** Prompt appears asking "Allow this command?"

### **Test 3: Blocked Commands (Should Fail)**

Test these commands should be **rejected**:

```bash
# Dangerous operations
git push --force origin master
docker system prune -a
```

**Expected:** Error message "This command is blocked by security policy"

### **Test 4: Directory Access**

Test file access:

```javascript
// Should work - in allowed directory
Read C:\Users\botts\Downloads\Visual Mapper\www\main.html

// Should ask - outside allowed directory
Read C:\Windows\System32\config
```

**Expected:** Allowed directory = no prompt, others = prompt or deny

---

## 🎯 Step 4: Configure MCP Servers (Optional)

MCP (Model Context Protocol) servers provide additional capabilities:

### **File System Access**
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\botts\\Downloads\\Visual Mapper"],
      "description": "File system access for Visual Mapper project"
    }
  }
}
```

### **Git Operations**
```json
{
  "mcpServers": {
    "git": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-git"],
      "cwd": "C:\\Users\\botts\\Downloads\\Visual Mapper",
      "description": "Git operations for Visual Mapper"
    }
  }
}
```

### **Web Search (For Research)**
```json
{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "YOUR_API_KEY_HERE"
      },
      "description": "Web search for documentation and research"
    }
  }
}
```

**Note:** MCP servers add tool definitions to Claude's context. Disable unused servers to save context window.

---

## 🔄 Step 5: Workflow Integration

### **Autonomous Testing Workflow**

With permissions configured, Claude can now:

```
1. Read test files
   ↓
2. Run `npm test` automatically (no prompt)
   ↓
3. Analyze failures
   ↓
4. Fix code
   ↓
5. Re-run tests automatically
   ↓
6. Ask user to validate on port 3000
   ↓
7. Request approval for `git commit`
   ↓
8. Request approval for `git push`
```

### **Local Development Loop**

```
1. Start dev server: `npm run dev` (auto-approved)
   ↓
2. Test frontend: `curl localhost:3000` (auto-approved)
   ↓
3. Test API: `curl localhost:8099/api/adb/devices` (auto-approved)
   ↓
4. Run E2E tests: `playwright test` (auto-approved)
   ↓
5. Make changes
   ↓
6. Repeat 2-4 automatically
```

---

## 🛠️ Troubleshooting

### **Issue: Commands Still Asking for Approval**

**Solution 1:** Check file location
```bash
# Windows
dir C:\Users\<USERNAME>\.claude.json

# macOS/Linux
ls -la ~/.claude.json
```

**Solution 2:** Validate JSON syntax
```bash
# Use online validator: https://jsonlint.com/
# Or use jq:
jq . ~/.claude.json
```

**Solution 3:** Restart Claude Code
- Close all Claude Code windows
- Restart VS Code
- Re-open project

### **Issue: MCP Servers Not Loading**

**Solution 1:** Check MCP server installation
```bash
# Test if npx can find the server
npx -y @modelcontextprotocol/server-filesystem --version
```

**Solution 2:** Check logs
- Open Claude Code output panel
- Look for MCP server initialization errors

**Solution 3:** Disable and re-enable
```json
{
  "mcpServers": {
    // Comment out problematic server
    // "filesystem": { ... }
  }
}
```

### **Issue: Directory Access Denied**

**Solution 1:** Check path format
```json
// Windows - use double backslashes
"C:\\Users\\botts\\Downloads\\Visual Mapper"

// Or use forward slashes
"C:/Users/botts/Downloads/Visual Mapper"

// macOS/Linux
"/home/user/visual-mapper"
```

**Solution 2:** Check directory exists
```bash
# Windows
dir "C:\Users\botts\Downloads\Visual Mapper"

# macOS/Linux
ls ~/visual-mapper
```

### **Issue: Too Many Permission Prompts**

**Solution:** Add commands to allowlist incrementally

```json
{
  "allowedCommands": [
    "ls",
    "git status"
    // Add more as needed
  ]
}
```

**Tip:** Monitor what Claude tries to run, add safe commands to allowlist

---

## 📊 Permission Levels Comparison

| Operation | No Config | Basic Config | Full Config |
|-----------|-----------|--------------|-------------|
| `ls` | ❓ Ask | ✅ Auto | ✅ Auto |
| `git status` | ❓ Ask | ✅ Auto | ✅ Auto |
| `npm test` | ❓ Ask | ❓ Ask | ✅ Auto |
| `playwright test` | ❓ Ask | ❓ Ask | ✅ Auto |
| `git commit` | ❓ Ask | ❓ Ask | ❓ Ask |
| `git push` | ❓ Ask | ❓ Ask | ❓ Ask |
| `rm -rf /` | ❓ Ask | ❓ Ask | 🚫 Blocked |

**Legend:**
- ✅ Auto = Runs without prompt
- ❓ Ask = Prompts for confirmation
- 🚫 Blocked = Completely denied

---

## 🎓 Advanced Configuration

### **Specialized Agents**

Configure different permission levels for different agent types:

```json
{
  "permissions": {
    "visual_mapper": {
      "agents": {
        "test-runner": {
          "allowedCommands": ["npm test", "playwright test", "pytest"],
          "allowedDirectories": ["C:\\Users\\botts\\Downloads\\Visual Mapper\\tests"]
        },
        "code-reviewer": {
          "allowedCommands": ["git diff", "git log", "git show"],
          "allowedDirectories": ["C:\\Users\\botts\\Downloads\\Visual Mapper"]
        },
        "implementer": {
          "allowedCommands": ["npm test", "git status", "git diff"],
          "allowedDirectories": [
            "C:\\Users\\botts\\Downloads\\Visual Mapper\\www",
            "C:\\Users\\botts\\Downloads\\Visual Mapper\\tests"
          ],
          "requireConfirmation": {
            "commands": ["git commit"]
          }
        }
      }
    }
  }
}
```

### **Time-Based Restrictions**

Require approval for destructive operations during work hours:

```json
{
  "permissions": {
    "visual_mapper": {
      "timeRestrictions": {
        "requireConfirmationDuring": {
          "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
          "hours": "09:00-17:00",
          "commands": ["git push", "docker build"]
        }
      }
    }
  }
}
```

### **Resource Limits**

Limit resource-intensive operations:

```json
{
  "permissions": {
    "visual_mapper": {
      "resourceLimits": {
        "maxConcurrentTests": 3,
        "maxMemoryPerCommand": "2GB",
        "maxExecutionTime": "10m"
      }
    }
  }
}
```

---

## 📋 Checklist: Configuration Complete

Use this checklist to verify setup:

- [ ] Created ~/.claude.json with Visual Mapper permissions
- [ ] Validated JSON syntax
- [ ] Tested read-only commands (should auto-approve)
- [ ] Tested write commands (should ask confirmation)
- [ ] Tested blocked commands (should deny)
- [ ] Configured MCP servers (optional)
- [ ] Restarted Claude Code
- [ ] Verified file access to project directories
- [ ] Tested autonomous test execution
- [ ] Tested local API access (curl localhost:3000)

---

## 🎉 Next Steps

Now that permissions are configured:

1. **Read Development Workflow** → [02_QUICK_START_GUIDE.md](02_QUICK_START_GUIDE.md)
2. **Understand Architecture** → [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md)
3. **Setup Local Environment** → [40_LOCAL_DEV_ENVIRONMENT.md](40_LOCAL_DEV_ENVIRONMENT.md)

---

## 📚 References

### **Claude Code Documentation**
- [MCP Server Configuration](https://modelcontextprotocol.io/quickstart/server)
- [Permission System](https://claudecode.ai/docs/permissions)
- [Best Practices](https://claudelog.com/faqs/how-to-setup-claude-code-mcp-servers/)

### **Visual Mapper Specific**
- [System Architecture](10_SYSTEM_ARCHITECTURE.md)
- [Testing Guide](41_TESTING_PLAYWRIGHT.md)
- [Local Development](40_LOCAL_DEV_ENVIRONMENT.md)

---

## 💡 Tips for Success

### **Do:**
- ✅ Start with minimal permissions, expand as needed
- ✅ Test configuration before relying on autonomous execution
- ✅ Document any custom commands you add
- ✅ Review blocked commands list periodically
- ✅ Use MCP servers for specialized capabilities

### **Don't:**
- ❌ Allow unrestricted file system access
- ❌ Auto-approve git push operations
- ❌ Skip testing after configuration changes
- ❌ Add commands to allowlist without understanding them
- ❌ Disable all safety checks for convenience

### **Common Mistakes:**
1. **Allowing too much** - Start restrictive, expand gradually
2. **Wrong path format** - Use double backslashes on Windows
3. **Not restarting Claude** - Changes require restart
4. **Invalid JSON** - Validate syntax before saving
5. **Forgetting to test** - Always test before relying on config

---

## 📝 Document Version

**Version:** 1.0.0
**Created:** 2025-12-21
**For Project Version:** Visual Mapper 0.0.1+
**Last Updated:** 2025-12-21

---

**Read Next:** [02_QUICK_START_GUIDE.md](02_QUICK_START_GUIDE.md)
**Read Previous:** [00_START_HERE.md](00_START_HERE.md)
