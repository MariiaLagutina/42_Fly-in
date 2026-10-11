# Simulation Challenge Maps

This collection contains carefully crafted maps designed to test different aspects of aircraft pathfinding algorithms, from basic navigation to complex optimization challenges.

## Map Categories

### 🟢 Easy Maps
**Target**: Beginners, basic algorithm testing
- `01_linear_path.txt` - Simple linear progression (2 aircraft)
- `02_simple_fork.txt` - Basic path splitting (3 aircraft)
- `03_basic_capacity.txt` - Introduction to capacity constraints (4 aircraft)

### 🟡 Medium Maps
**Target**: Intermediate challenges, algorithm optimization
- `01_dead_end_trap.txt` - Dead ends that can trap naive algorithms (5 aircraft)
- `02_circular_loop.txt` - Circular paths with restricted hubs (6 aircraft)
- `03_priority_puzzle.txt` - Optimal path selection with priority hubs (4 aircraft)

### 🔴 Hard Maps
**Target**: Advanced algorithms, stress testing
- `01_maze_nightmare.txt` - Complex maze with multiple traps and loops (8 aircraft)
- `02_capacity_hell.txt` - Extreme capacity constraints requiring careful timing (12 aircraft)
- `03_ultimate_challenge.txt` - **THE ULTIMATE TEST** - All challenges combined (15 aircraft)

### ⚫ Challenger Maps
**Target**: Research and algorithmic limits exploration
- `01_the_impossible_dream.txt` - **THE IMPOSSIBLE DREAM** - Quasi-unsolvable challenge (25 aircraft)

> ⚠️ **WARNING**: Challenger maps are designed to push algorithmic limits and may not be solvable by most implementations. They are intended for research, stress testing, and algorithmic exploration rather than validation. The goal is to challenge the boundaries of what's possible, not to pass evaluation criteria.

> 🏆 **CHALLENGE RECORD**: The reference implementation solves "The Impossible Dream" in **45 turns**. Can you beat this record? This serves as a benchmark for algorithmic optimization and provides a concrete goal for advanced implementations.

## Challenge Types Covered

### 🎯 **Dead End Traps**
Maps contain paths that lead nowhere, testing if algorithms can backtrack or avoid getting stuck.

### 🔄 **Circular Loops**
Cycles in the graph that can cause infinite loops in poorly designed algorithms.

### ⚡ **Capacity Constraints**
- Hub capacity limits (`max_drones`)
- Lane capacity limits (`max_link_capacity`)
- Timing-based bottlenecks

### 🚀 **Hub Type Optimization**
- `normal`: Standard 1-turn movement
- `restricted`: 2-turn movement (slow but sometimes necessary)
- `priority`: 1-turn movement but should be preferred
- `blocked`: Completely inaccessible

### 🧩 **Complex Topology**
- Multiple valid paths with different costs
- Convergence points requiring coordination
- Multi-layer challenges

## Testing Strategy

1. **Start with Easy**: Ensure basic functionality works
2. **Progress to Medium**: Test algorithm robustness
3. **Challenge with Hard**: Stress test optimization and edge cases
4. **Ultimate Test**: `03_ultimate_challenge.txt` combines all difficulties

## Expected Behavior

All maps are designed to be solvable with a well-implemented algorithm. However:

- **Easy maps**: Should solve quickly with any reasonable approach
- **Medium maps**: May require backtracking, path optimization, or capacity management
- **Hard maps**: Demand sophisticated algorithms with proper conflict resolution and optimization

## Performance Benchmarks

- **Easy**: < 10 simulation turns typically
- **Medium**: 10-30 simulation turns depending on optimization
- **Hard**: 30+ simulation turns, focus on finding valid solutions
- **Challenger**: **Record to beat: 41 turns** for "The Impossible Dream" - designed for algorithmic research

## Visual Representation

Maps use color coding for enhanced understanding:
- 🟢 **Green**: Start/End hubs
- 🔵 **Blue**: Normal paths
- 🟡 **Yellow**: Junction/merge points
- 🟠 **Orange**: Bottlenecks/gates
- 🔴 **Red**: Dead ends/traps
- 🟣 **Purple**: Restricted hubs
- 🔵 **Cyan**: Priority hubs

Use the `--visual` flag to see colored terminal output during simulation!
