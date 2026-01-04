/**
 * Step Editor Component
 * Visual Mapper v0.0.1
 * 
 * Reusable component for rendering and editing flow steps.
 * Consolidates logic from flows.html and flow-wizard.js
 */

export class StepEditor {
    constructor(container, options = {}) {
        this.container = container;
        this.steps = options.steps || [];
        this.onChange = options.onChange || (() => {});
        this.readOnly = options.readOnly || false;
    }

    setSteps(steps) {
        this.steps = steps;
        this.render();
    }

    getSteps() {
        return this.steps;
    }

    addStep(stepType) {
        if (this.readOnly) return;

        const newStep = {
            step_type: stepType,
            description: `New ${stepType} step`,
            retry_on_failure: false,
            max_retries: 3
        };

        // Initialize defaults
        if (stepType === 'tap') { newStep.x = 0; newStep.y = 0; }
        else if (stepType === 'swipe') { newStep.start_x = 0; newStep.start_y = 0; newStep.end_x = 0; newStep.end_y = 0; newStep.duration = 500; }
        else if (stepType === 'type_text') { newStep.text = ''; }
        else if (stepType === 'wait') { newStep.duration = 1000; }
        else if (stepType === 'launch_app') { newStep.package = ''; }
        else if (stepType === 'capture_sensors') { newStep.sensor_ids = []; }

        this.steps.push(newStep);
        this.render();
        this.onChange(this.steps);
    }

    updateStep(index, field, value) {
        if (this.readOnly || !this.steps[index]) return;
        this.steps[index][field] = value;
        this.onChange(this.steps);
        // Note: We might not want to re-render on every keystroke to avoid losing focus
        // For text inputs, maybe use 'change' event instead of 'input'
    }

    deleteStep(index) {
        if (this.readOnly || !this.steps[index]) return;
        if (!confirm('Delete this step?')) return;
        this.steps.splice(index, 1);
        this.render();
        this.onChange(this.steps);
    }

    moveStep(index, direction) {
        if (this.readOnly) return;
        const newIndex = index + direction;
        if (newIndex < 0 || newIndex >= this.steps.length) return;
        
        [this.steps[index], this.steps[newIndex]] = [this.steps[newIndex], this.steps[index]];
        this.render();
        this.onChange(this.steps);
    }

    render() {
        if (this.steps.length === 0) {
            this.container.innerHTML = '<p class="empty-steps">No steps defined. Add one below.</p>';
            return;
        }

        this.container.innerHTML = this.steps.map((step, index) => this._renderStep(step, index)).join('');
        
        // Attach event listeners
        this.container.querySelectorAll('input, select').forEach(input => {
            input.addEventListener('change', (e) => {
                const index = parseInt(e.target.dataset.index);
                const field = e.target.dataset.field;
                let value = e.target.type === 'number' ? parseFloat(e.target.value) : e.target.value;
                if (field === 'sensor_ids') {
                    value = value.split(',').map(s => s.trim()).filter(s => s);
                }
                this.updateStep(index, field, value);
            });
        });

        this.container.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.closest('button').dataset.index);
                this.deleteStep(index);
            });
        });

        this.container.querySelectorAll('.btn-move-up').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.closest('button').dataset.index);
                this.moveStep(index, -1);
            });
        });

        this.container.querySelectorAll('.btn-move-down').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt(e.target.closest('button').dataset.index);
                this.moveStep(index, 1);
            });
        });
    }

    _renderStep(step, index) {
        const typeLabels = {
            'tap': '👆 Tap', 'swipe': '👉 Swipe', 'type_text': '⌨️ Type', 
            'wait': '⏱️ Wait', 'launch_app': '🚀 Launch', 'capture_sensors': '📊 Capture'
        };

        const controls = this.readOnly ? '' : `
            <div class="step-controls">
                <button type="button" class="btn-icon btn-move-up" data-index="${index}" ${index === 0 ? 'disabled' : ''}>↑</button>
                <button type="button" class="btn-icon btn-move-down" data-index="${index}" ${index === this.steps.length - 1 ? 'disabled' : ''}>↓</button>
                <button type="button" class="btn-icon btn-delete" data-index="${index}">✕</button>
            </div>
        `;

        return `
            <div class="step-card" data-index="${index}">
                <div class="step-header">
                    <span class="step-badge">${typeLabels[step.step_type] || step.step_type}</span>
                    ${controls}
                </div>
                <div class="step-fields">
                    <div class="form-group full-width">
                        <label>Description</label>
                        <input type="text" class="form-control" value="${this._escape(step.description || '')}" 
                               data-index="${index}" data-field="description" ${this.readOnly ? 'disabled' : ''}>
                    </div>
                    ${this._renderTypeFields(step, index)}
                </div>
            </div>
        `;
    }

    _renderTypeFields(step, index) {
        const commonAttrs = `data-index="${index}" ${this.readOnly ? 'disabled' : ''} class="form-control"`;
        
        switch (step.step_type) {
            case 'tap':
                return `
                    <div class="form-group"><label>X</label><input type="number" ${commonAttrs} data-field="x" value="${step.x}"></div>
                    <div class="form-group"><label>Y</label><input type="number" ${commonAttrs} data-field="y" value="${step.y}"></div>
                `;
            case 'wait':
                return `<div class="form-group"><label>Duration (ms)</label><input type="number" ${commonAttrs} data-field="duration" value="${step.duration}"></div>`;
            case 'type_text':
                return `<div class="form-group full-width"><label>Text</label><input type="text" ${commonAttrs} data-field="text" value="${this._escape(step.text)}"></div>`;
            case 'launch_app':
                return `<div class="form-group full-width"><label>Package</label><input type="text" ${commonAttrs} data-field="package" value="${this._escape(step.package)}"></div>`;
            case 'swipe':
                return `
                    <div class="form-group"><label>Start X</label><input type="number" ${commonAttrs} data-field="start_x" value="${step.start_x}"></div>
                    <div class="form-group"><label>Start Y</label><input type="number" ${commonAttrs} data-field="start_y" value="${step.start_y}"></div>
                    <div class="form-group"><label>End X</label><input type="number" ${commonAttrs} data-field="end_x" value="${step.end_x}"></div>
                    <div class="form-group"><label>End Y</label><input type="number" ${commonAttrs} data-field="end_y" value="${step.end_y}"></div>
                    <div class="form-group"><label>Duration</label><input type="number" ${commonAttrs} data-field="duration" value="${step.duration}"></div>
                `;
            case 'capture_sensors':
                return `<div class="form-group full-width"><label>Sensor IDs (comma-sep)</label><input type="text" ${commonAttrs} data-field="sensor_ids" value="${(step.sensor_ids || []).join(', ')}"></div>`;
            default:
                return '';
        }
    }

    _escape(str) {
        if (!str) return '';
        return str.replace(/"/g, '&quot;');
    }
}
