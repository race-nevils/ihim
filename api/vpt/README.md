# VPT (Value Per Token) Calculation Module

## Overview

This module implements the VPT (Value Per Token) measurement system for iHIM, providing quantitative efficiency and quality metrics for AI interactions.

## Formula

```
VPT = (composite_value_score / total_tokens) × 1000
```

### Composite Value Score (0-100)

Weighted combination of 7 metrics:

```
composite_score =
  (success × 20) +                    // Did it work? (boolean → 0 or 20)
  (outcome_quality × 4 × 20) +        // Quality (1-5 scale → 0-20)
  (efficiency_ratio × 25) +           // Effective/total actions (0-1 → 0-25)
  (-dead_ends × 5) +                  // Penalty for dead ends (cap at -15)
  (-pivots × 3) +                     // Penalty for pivots (cap at -9)
  (reusability × 3 × 20) +            // Future value (1-5 → 0-15)
  (learning_value × 3 × 20)           // Heuristic generation (1-5 → 0-15)
```

## API Endpoints

### GET /api/vpt/calculate

Calculate VPT using query parameters.

**Example:**
```
GET /api/vpt/calculate?success=true&outcome_quality=5&efficiency_ratio=0.9&dead_ends=0&pivots=1&total_tokens=3450&reusability=5&learning_value=4
```

**Response:**
```json
{
  "success": true,
  "composite_score": 86.5,
  "vpt_score": 25.07,
  "rating": "★★★",
  "interpretation": "Good, room for improvement",
  "details": {
    "success": true,
    "outcome_quality": 5,
    "efficiency_ratio": 0.9,
    "dead_ends": 0,
    "pivots": 1,
    "total_tokens": 3450,
    "reusability": 5,
    "learning_value": 4
  }
}
```

### POST /api/vpt/calculate

Calculate VPT using JSON body.

**Example:**
```bash
curl -X POST http://localhost:7777/api/vpt/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "success": true,
    "outcome_quality": 5,
    "efficiency_ratio": 0.9,
    "dead_ends": 0,
    "pivots": 1,
    "total_tokens": 3450,
    "reusability": 5,
    "learning_value": 4
  }'
```

## Rating System

| VPT Range | Rating | Interpretation |
|-----------|--------|----------------|
| 100+ | ★★★★★ | Exceptional efficiency |
| 50-100 | ★★★★ | High value |
| 25-50 | ★★★ | Good, room for improvement |
| 10-25 | ★★ | Acceptable, review for optimization |
| < 10 | ★ | Low efficiency, investigate |

## Functions

### `calculate_composite_score()`

Calculate weighted value score (0-100).

**Parameters:**
- `success` (bool): Did the task succeed?
- `outcome_quality` (int 1-5): Quality of solution
- `efficiency_ratio` (float 0-1): Effective/total actions
- `dead_ends` (int): Number of dead-end paths
- `pivots` (int): Number of strategy pivots
- `reusability` (int 1-5): Future reusability value (default: 3)
- `learning_value` (int 1-5): Heuristic generation value (default: 3)

**Returns:** float (0-100)

### `calculate_vpt()`

Calculate VPT from composite score and tokens.

**Parameters:**
- `composite_score` (float): Composite value score (0-100)
- `total_tokens` (int): Total tokens used

**Returns:** float (VPT score)

### `get_vpt_rating()`

Get star rating for a VPT score.

**Parameters:**
- `vpt_score` (float): Calculated VPT score

**Returns:** str (★ to ★★★★★)

### `estimate_tokens_from_commands()`

Estimate tokens when exact count unavailable (500 tokens per command).

**Parameters:**
- `total_commands` (int): Number of commands

**Returns:** int (estimated tokens)

### `calculate_vpt_full()`

Convenience function that returns all three values.

**Returns:** tuple (composite_score, vpt_score, rating)

## Example Test Results

### Test 1: High Value Scenario
```
Composite: 86.5 | VPT: 25.07 | Rating: ★★★ | Good, room for improvement
```

### Test 2: Low Value Scenario
```
Composite: 1.0 | VPT: 0.05 | Rating: ★ | Low efficiency, investigate
```

### Test 3: Exceptional Efficiency
```
Composite: 95.0 | VPT: 190.0 | Rating: ★★★★★ | Exceptional efficiency
```

### Test 4: Medium Effort Task
```
Composite: 54.0 | VPT: 10.8 | Rating: ★★ | Acceptable, review for optimization
```

## Files

- `calculator.py` - Core VPT calculation functions
- `__init__.py` - Module initialization
- `README.md` - This documentation

## Design Reference

See `C:\Users\<user>\workspace\IHIM\data\VPT_DESIGN.md` for the full VPT system design specification.
