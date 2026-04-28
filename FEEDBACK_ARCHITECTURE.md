# Feedback Loop Architecture

## Current Architecture (Basic Feedback)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYSIS CYCLE (every 30s)                   │
│                                                                  │
│  Events (t) ────┐                                               │
│                 │                                               │
│                 ├──▶ Build Prompt ──▶ Claude Sonnet 4.5 ──┐    │
│                 │         │                                 │    │
│  Last Result    │         │                                 │    │
│  (t-1) ─────────┘         │                                 │    │
│    ▲                      │                                 │    │
│    │                Previous Analysis                       │    │
│    │                (JSON result)                           │    │
│    │                      │                                 │    │
│    │                      ▼                                 │    │
│    │                  "If anomaly                           │    │
│    │              still present,                            │    │
│    │           maintain ANOMALY status"                     │    │
│    │                                                         │    │
│    │                                                         ▼    │
│    └────────────────── New Result ◀────────── Analysis ─────┘    │
│                           (JSON)              (+ Reasoning)       │
│                                                                  │
│  Stored but UNUSED:                                             │
│  • result_history (last 50)  ← NOT sent to model              │
│  • reasoning traces          ← NOT analyzed                    │
│  • confidence trends         ← NOT learned from                │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                    Email → Human Operator
                    (No feedback mechanism)
```

**Feedback Loop Status:** 🟡 **1-STEP** (only previous result)

---

## Ideal Architecture (Continuous Improvement)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        LEARNING ANALYSIS SYSTEM                           │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────┐         │
│  │              ANALYSIS CYCLE (every 30s)                      │         │
│  │                                                              │         │
│  │  Current Events ────┐                                       │         │
│  │                     │                                       │         │
│  │  Recent History ────┤                                       │         │
│  │  (last 5 analyses)  │                                       │         │
│  │                     │                                       │         │
│  │  Validated ─────────┼──▶ Enhanced Prompt ──▶ Claude ───┐   │         │
│  │  Examples           │         Builder              4.5  │   │         │
│  │  (HITL feedback)    │            │                      │   │         │
│  │                     │            ▼                      │   │         │
│  │  Similar Past ──────┘    System Prompt                 │   │         │
│  │  Cases                   (optimized)                    │   │         │
│  │  (pattern match)              │                         │   │         │
│  │                               │                         │   │         │
│  │                               ▼                         │   │         │
│  │                       "Analyze trends:                  │   │         │
│  │                    confidence rising? metrics           │   │         │
│  │                    improving? Similar to                │   │         │
│  │                    Case #1234 which was                 │   │         │
│  │                    confirmed true positive"             │   │         │
│  │                                                          │   │         │
│  │                                                          ▼   │         │
│  │                                                    Analysis  │         │
│  │                                                    Result    │         │
│  │                                                    + Reason  │         │
│  └──────────────────────────────────────────────────────┬──────┘         │
│                                                          │                │
│                                                          ▼                │
│  ┌──────────────────────────────────────────────────────────────┐        │
│  │                    PERSISTENT STORE                           │        │
│  │                  (DynamoDB / PostgreSQL)                      │        │
│  │                                                               │        │
│  │  Stores:                                                      │        │
│  │  • All analysis results (cycle_id, events, result)           │        │
│  │  • Extended thinking traces                                  │        │
│  │  • Human feedback (correct? false positive?)                 │        │
│  │  • Ground truth outcomes (incident? resolved?)               │        │
│  │  • Confidence calibration (predicted vs actual)              │        │
│  │                                                               │        │
│  │  Enables:                                                     │        │
│  │  • Pattern matching (vector search)                          │        │
│  │  • Trend analysis (6-12 months)                              │        │
│  │  • Accuracy metrics (precision, recall, F1)                  │        │
│  │  • Model performance tracking                                │        │
│  └──────────────────────────────────────────────────────────────┘        │
│                             │                │                            │
│                             │                │                            │
│              ┌──────────────┘                └────────────┐               │
│              ▼                                            ▼               │
│  ┌────────────────────────┐                  ┌─────────────────────────┐ │
│  │   PROMPT OPTIMIZER     │                  │   DASHBOARD + HITL      │ │
│  │   (Weekly/Monthly)     │                  │   (Real-time)           │ │
│  │                        │                  │                         │ │
│  │  • Analyzes feedback   │                  │  • Show analysis result │ │
│  │  • Identifies patterns │                  │  • Capture feedback:    │ │
│  │    in false positives  │                  │    ☑ Correct            │ │
│  │  • Suggests threshold  │                  │    ☐ False Positive     │ │
│  │    adjustments         │◀─────────────────│    ☐ Missed Anomaly     │ │
│  │  • Generates few-shot  │   Human Review   │    💬 Comments          │ │
│  │    examples            │                  │                         │ │
│  │  • Updates system      │                  │  • Link to incident     │ │
│  │    prompt              │                  │    management system    │ │
│  └────────────────────────┘                  └─────────────────────────┘ │
│              │                                                            │
│              ▼                                                            │
│  ┌────────────────────────┐                                              │
│  │  REFINED SYSTEM PROMPT │                                              │
│  │                        │                                              │
│  │  • Updated thresholds  │                                              │
│  │  • New pattern rules   │                                              │
│  │  • Few-shot examples   │                                              │
│  │  • Seasonal adjustments│                                              │
│  └────────────────────────┘                                              │
│              │                                                            │
│              └───────────────┐                                           │
│                              │                                           │
│                              ▼                                           │
│                      Next Analysis Cycle                                 │
│                      (uses improved prompt)                              │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

**Feedback Loop Status:** 🟢 **CONTINUOUS LEARNING**

---

## Key Differences

| Aspect | Current | Ideal |
|--------|---------|-------|
| **Temporal Context** | 1 previous result | 5-10 recent analyses + trends |
| **Historical Knowledge** | Ephemeral (lost on restart) | Persistent (6-12 months) |
| **Human Feedback** | None | HITL validation on every alert |
| **Ground Truth** | Unknown | Tracked via incident outcomes |
| **Learning Mechanism** | Static prompt | Adaptive prompt refinement |
| **Pattern Matching** | None | Vector search for similar cases |
| **Accuracy Metrics** | Confidence only | Precision, recall, F1 |
| **Prompt Evolution** | Manual updates | Automated optimization |
| **Reasoning Analysis** | Logged but unused | Analyzed for quality |
| **Model Selection** | Fixed (Sonnet 4.5) | Could adapt based on performance |

---

## Implementation Roadmap

### Phase 1: Enhanced Temporal Context (Week 1)
```python
# Quick win - use existing result_history
def _build_prompt_with_history(self):
    recent = list(self.result_history)[-5:]
    # Include trend analysis in prompt
    # "UC1 confidence: 0.75 → 0.82 → 0.87 (rising)"
```
**Benefit:** Better awareness of trends, smoother transitions

### Phase 2: Human Feedback Capture (Week 2)
```python
# Add to dashboard
@app.post("/api/feedback")
async def submit_feedback(cycle_id, is_correct, comments):
    store.save_feedback(cycle_id, is_correct, comments)
```
**Benefit:** Ground truth for measuring accuracy

### Phase 3: Persistent Storage (Week 3-4)
```python
# DynamoDB table design
AnalysisHistory:
  - cycle_id (PK)
  - timestamp
  - events_json
  - result_json
  - reasoning_text
  - feedback (nullable)
  - ground_truth (nullable)
```
**Benefit:** Long-term learning foundation

### Phase 4: Pattern Matching (Week 5-6)
```python
# Before each analysis, find similar past cases
similar_cases = store.query_similar_patterns(
    current_events,
    use_embeddings=True,
    limit=3
)
# Add to prompt as examples
```
**Benefit:** Learn from institutional knowledge

### Phase 5: Prompt Optimization (Week 7-8)
```python
# Weekly job analyzes feedback
optimizer = PromptOptimizer(store)
suggestions = optimizer.analyze_false_positives()
# Human reviews and approves prompt changes
```
**Benefit:** Continuous improvement, reduced false positives

### Phase 6: Automated Metrics (Week 9)
```python
# Dashboard shows:
# - Precision: 92.3%
# - Recall: 87.6%
# - F1 Score: 89.9%
# - Trend: +2.1% this month
```
**Benefit:** Quantify improvement over time

---

## Expected Outcomes

### Month 1 (Phases 1-3)
- ✅ Better temporal awareness (trends visible)
- ✅ Human feedback loop established
- ✅ Persistent storage operational
- 📊 Baseline accuracy measured

### Month 3 (Phases 4-5)
- ✅ Pattern matching from historical cases
- ✅ First round of prompt optimization
- 📊 5-10% reduction in false positives
- 📊 2-5% improvement in recall

### Month 6
- ✅ Fully automated learning pipeline
- ✅ Self-tuning thresholds
- 📊 15-20% reduction in false positives
- 📊 10% improvement in overall accuracy
- 📊 Operator time saved: 30-40%

### Month 12
- ✅ Mature learning system
- ✅ Seasonal pattern recognition
- 📊 25-30% reduction in false positives
- 📊 Converged on optimal thresholds
- 📊 ROI: 3-5x cost savings vs manual monitoring

---

## Technical Implementation Examples

### Example 1: Multi-Cycle History in Prompt

**Before:**
```python
prompt = f"Analyze these events:\n{event_summary}"
if self.last_result:
    prompt += f"\nPrevious: {self.last_result}"
```

**After:**
```python
prompt = f"Analyze these events:\n{event_summary}"

# Add trend context
recent_5 = list(self.result_history)[-5:]
if recent_5:
    prompt += "\n\n=== RECENT HISTORY (last 5 cycles) ===\n"
    for r in recent_5:
        uc1 = r.get("uc1", {})
        prompt += f"Cycle {r['cycle']}: UC1={uc1['status']} (conf={uc1['confidence']:.2f})\n"
    
    # Trend analysis
    confidences = [r.get("uc1", {}).get("confidence", 0) for r in recent_5]
    trend = "rising" if confidences[-1] > confidences[0] else "falling"
    prompt += f"\nTrend: UC1 confidence {trend} from {confidences[0]:.2f} to {confidences[-1]:.2f}\n"
    prompt += "If confidence is rising and anomaly persists, maintain ANOMALY status.\n"
```

### Example 2: HITL Feedback Storage

```python
# Database schema
class AnalysisFeedback:
    cycle_id: int
    timestamp: datetime
    operator_id: str
    uc1_correct: bool
    uc2_correct: bool
    false_positive: bool
    missed_anomaly: bool
    incident_link: Optional[str]
    comments: Optional[str]
    
# Dashboard endpoint
@app.post("/api/feedback/{cycle_id}")
async def submit_feedback(cycle_id: int, feedback: AnalysisFeedback):
    # Store in database
    db.save_feedback(feedback)
    
    # If false positive, flag for review
    if feedback.false_positive:
        alert_slack_channel(
            f"False positive reported for cycle {cycle_id}. "
            f"Pattern: {get_pattern(cycle_id)}"
        )
    
    return {"status": "saved"}
```

### Example 3: Pattern Matching for Similar Cases

```python
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class PatternMatcher:
    def find_similar_cases(self, current_events: dict, top_k=3):
        """Find past analyses with similar event patterns."""
        
        # Extract features from current events
        current_vector = self._vectorize_events(current_events)
        
        # Query database for past cases with high confidence and feedback
        past_cases = db.query(
            "SELECT * FROM analyses WHERE feedback IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 100"
        )
        
        # Calculate similarity
        similarities = []
        for case in past_cases:
            past_vector = self._vectorize_events(case.events)
            similarity = cosine_similarity(
                current_vector.reshape(1, -1),
                past_vector.reshape(1, -1)
            )[0][0]
            similarities.append((similarity, case))
        
        # Return top-k most similar
        similarities.sort(reverse=True)
        return [case for _, case in similarities[:top_k]]
    
    def _vectorize_events(self, events: dict) -> np.ndarray:
        """Convert events to feature vector."""
        features = []
        # Extract key metrics
        features.append(events.get("capacity_pct", 100) / 100)
        features.append(events.get("days_of_supply", 30) / 30)
        features.append(events.get("delay_hours", 0) / 100)
        # ... more features
        return np.array(features)
```

### Example 4: Prompt Optimization Based on Feedback

```python
class PromptOptimizer:
    def analyze_false_positives(self, days=30):
        """Identify common patterns in false positives."""
        
        fp_cases = db.query(
            "SELECT * FROM analyses WHERE feedback.false_positive = true "
            f"AND timestamp > NOW() - INTERVAL '{days} days'"
        )
        
        # Analyze patterns
        insights = {
            "capacity_threshold_too_high": 0,
            "delay_threshold_too_low": 0,
            "inventory_overreaction": 0,
        }
        
        for case in fp_cases:
            events = case.events
            # Check if capacity was borderline
            if 45 < events.get("capacity_pct", 100) < 55:
                insights["capacity_threshold_too_high"] += 1
            # ... more pattern checks
        
        # Generate recommendations
        recommendations = []
        if insights["capacity_threshold_too_high"] > 5:
            recommendations.append(
                "Consider lowering capacity threshold from 50% to 40%. "
                f"Found {insights['capacity_threshold_too_high']} false positives "
                "with capacity between 45-55%."
            )
        
        return recommendations
    
    def generate_updated_prompt(self, recommendations):
        """Apply recommendations to system prompt."""
        # Human reviews and approves before deployment
        updated_prompt = SYSTEM_PROMPT
        
        for rec in recommendations:
            if "capacity threshold from 50% to 40%" in rec:
                updated_prompt = updated_prompt.replace(
                    "capacity_pct below 50%",
                    "capacity_pct below 40%"
                )
        
        return updated_prompt
```

---

## Conclusion

The current system has **basic temporal feedback** but lacks **continuous improvement** mechanisms. To achieve true learning:

1. **Immediate:** Add multi-cycle history to prompts (1 day effort)
2. **Short-term:** Build HITL feedback capture (1 week effort)
3. **Medium-term:** Implement persistent storage (2 weeks effort)
4. **Long-term:** Build prompt optimization pipeline (1 month effort)

The ROI is clear: **25-30% reduction in false positives** within 6 months, **operator time saved 30-40%**, and **converged optimal accuracy** within 12 months.
