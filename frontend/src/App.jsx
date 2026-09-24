import React, { useState, useEffect, useRef } from 'react';
import { 
  UploadCloud, Activity, LayoutGrid, CheckCircle, Circle, FileText, Download, 
  Hexagon, X, Layers, MousePointer2, Maximize2, Search, Bell, Database, 
  Archive, Settings, HelpCircle, Save, FileOutput, ZoomIn, ZoomOut, Eye, 
  Edit3, Trash2, RotateCcw, Plus, Eraser, Info, Sparkles, Filter, RefreshCw,
  CheckCircle2, FolderDown, ShieldCheck, HardDrive, FileCheck
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';

const calculatePolygonArea = (points) => {
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    let j = (i + 1) % points.length;
    area += points[i].x * points[j].y;
    area -= points[j].y * points[i].y;
  }
  return Math.abs(area / 2);
};

const calculatePolygonPerimeter = (points) => {
  let perimeter = 0;
  for (let i = 0; i < points.length; i++) {
    let j = (i + 1) % points.length;
    let dx = points[j].x - points[i].x;
    let dy = points[j].y - points[i].y;
    perimeter += Math.sqrt(dx * dx + dy * dy);
  }
  return perimeter;
};

const calculateCircularity = (area, perimeter) => {
  if (perimeter === 0) return 0;
  const circ = (4 * Math.PI * area) / (perimeter * perimeter);
  return Math.min(circ, 1.0);
};

const calculateCentroid = (points) => {
  if (!points || points.length === 0) return [256, 256];
  let sumX = 0;
  let sumY = 0;
  points.forEach(p => {
    sumX += p.x;
    sumY += p.y;
  });
  return [Math.round(sumX / points.length), Math.round(sumY / points.length)];
};

export default function App() {
  const [file, setFile] = useState(null);
  const [filename, setFilename] = useState('');
  const [preview, setPreview] = useState(null);
  const [tiles, setTiles] = useState([]);
  const [originalTilesBackup, setOriginalTilesBackup] = useState({});
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [selectedTileName, setSelectedTileName] = useState(null);
  const [history, setHistory] = useState([]);
  
  const [viewHeatmap, setViewHeatmap] = useState(false);
  const [showConfidence, setShowConfidence] = useState(false);
  const [tileFilter, setTileFilter] = useState('detected'); // 'detected' | 'all'

  // Modal Annotation & Tool State
  const [toolMode, setToolMode] = useState('inspect'); // 'inspect' | 'freehand' | 'eraser'
  const [viewMode, setViewMode] = useState('vector'); // 'vector' | 'saliency' | 'burned'
  const [showLabels, setShowLabels] = useState(true);
  const [currentPath, setCurrentPath] = useState([]);
  const [hoveredCellId, setHoveredCellId] = useState(null);
  const [selectedCellId, setSelectedCellId] = useState(null);
  const [cellFilter, setCellFilter] = useState('all'); // 'all' | 'ai' | 'manual'
  const [undoStack, setUndoStack] = useState([]);
  const svgRef = useRef(null);

  // Training Mask Export & Approval State
  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [maskSaving, setMaskSaving] = useState(false);
  const [savedMaskResult, setSavedMaskResult] = useState(null);
  const [trainingDatasetCount, setTrainingDatasetCount] = useState(0);
  const [showDatasetModal, setShowDatasetModal] = useState(false);
  const [datasetList, setDatasetList] = useState([]);

  // Canvas Pan/Zoom state
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });

  const activeTile = tiles.find(t => t.tile_name === selectedTileName);

  useEffect(() => {
    setScale(1);
    setPan({ x: 0, y: 0 });
  }, [preview, results?.heatmap, viewHeatmap]);

  // Load existing training dataset count on startup
  useEffect(() => {
    fetchTrainingDataset();
  }, []);

  const fetchTrainingDataset = async () => {
    try {
      const res = await fetch("http://localhost:8000/training-data/list");
      if (res.ok) {
        const data = await res.json();
        setTrainingDatasetCount(data.count || 0);
        setDatasetList(data.items || []);
      }
    } catch (e) {
      console.warn("Could not fetch training dataset count:", e);
    }
  };

  // Recompute global results whenever tiles change
  const recomputeStats = (currentTiles) => {
    let allCells = [];
    currentTiles.forEach(t => {
      if (t.cells && t.cells.length > 0) {
        allCells.push(...t.cells);
      }
    });

    const total = allCells.length;
    const areas = allCells.map(c => c.area);
    const circs = allCells.map(c => c.circularity);
    const avgArea = total > 0 ? areas.reduce((a, b) => a + b, 0) / total : 0;
    const avgCirc = total > 0 ? circs.reduce((a, b) => a + b, 0) / total : 0;

    setResults(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        total_cells: total,
        average_size: avgArea,
        average_circularity: avgCirc,
        areas: areas,
        circularities: circs
      };
    });
  };

  const handleFileChange = async (e) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      setFile(selected);
      setFilename(selected.name);
      setResults(null);
      setTiles([]);
      setOriginalTilesBackup({});
      setProgress(0);
      setError(null);
      setViewHeatmap(false);
      setUndoStack([]);
      setSavedMaskResult(null);
      
      const formData = new FormData();
      formData.append("file", selected);
      try {
        const res = await fetch("http://localhost:8000/preview", { method: "POST", body: formData });
        if (res.ok) {
          const data = await res.json();
          setPreview(data.preview);
        }
      } catch (err) {
        console.error("Preview generation failed:", err);
      }
    }
  };

  const runInference = async () => {
    if (!file) return;
    
    if ("Notification" in window && Notification.permission !== "granted" && Notification.permission !== "denied") {
      Notification.requestPermission();
    }

    setLoading(true);
    setError(null);
    setTiles([]);
    setOriginalTilesBackup({});
    setResults(null);
    setProgress(0);
    setViewHeatmap(false);
    setUndoStack([]);
    setSavedMaskResult(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("model_type", "unetplusplus");

    try {
      const response = await fetch("http://localhost:8000/predict", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error("Inference failed");

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let currentTiles = [];
      let initialBackups = {};

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); 

        for (const line of lines) {
          if (line.trim()) {
            try {
              const data = JSON.parse(line);
              if (data.type === 'progress') {
                setProgress(data.progress * 100);
                if (data.tile) {
                  currentTiles.push(data.tile);
                  initialBackups[data.tile.tile_name] = JSON.parse(JSON.stringify(data.tile.cells));
                  setTiles([...currentTiles]);
                  setOriginalTilesBackup({ ...initialBackups });
                }
              } else if (data.type === 'final') {
                setResults(data);
                const sessionRecord = {
                  id: Date.now(),
                  filename: file.name,
                  model: 'unetplusplus',
                  cells: data.total_cells,
                  tiles: currentTiles,
                  timestamp: new Date().toLocaleTimeString(),
                  avgArea: data.average_size,
                  avgCirc: data.average_circularity
                };
                setHistory(prev => [sessionRecord, ...prev].slice(0, 10));
                
                if ("Notification" in window && Notification.permission === "granted") {
                  new Notification("Analysis Complete", {
                    body: `OCLAST has finished processing ${file.name}. Detected ${data.total_cells} cells.`,
                    icon: "/vite.svg"
                  });
                }
              }
            } catch (e) {
              console.error("JSON parse error on line:", line, e);
            }
          }
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setProgress(100);
    }
  };

  const downloadCSV = (tilesData) => {
    if (!tilesData || tilesData.length === 0) return;
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "TileName,CellID,Area_px2,Circularity,Type\n";
    tilesData.forEach(t => {
      if (t.cells && t.cells.length > 0) {
        t.cells.forEach(c => {
          csvContent += `${t.tile_name},${c.id},${c.area.toFixed(2)},${c.circularity.toFixed(3)},${c.manual ? 'Manual' : 'AI_Predicted'}\n`;
        });
      }
    });
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `oclast_osteoclasts_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // --- TRAINING MASK APPROVAL & EXPORT LOGIC ---
  const handleApproveAndSaveMask = async () => {
    if (!filename || tiles.length === 0) return;

    setMaskSaving(true);
    setError(null);

    const payload = {
      filename: filename,
      orig_width: results?.orig_width || (preview ? 1600 : 1024),
      orig_height: results?.orig_height || (preview ? 1200 : 1024),
      tiles: tiles
    };

    try {
      const res = await fetch("http://localhost:8000/save-training-mask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (!res.ok) throw new Error("Failed to generate and save training mask");
      const data = await res.json();
      setSavedMaskResult(data);
      setTrainingDatasetCount(data.total_dataset_count);

      // Trigger automatic browser download of the .tif file for the user
      const downloadLink = document.createElement("a");
      downloadLink.href = data.download_url;
      downloadLink.setAttribute("download", data.mask_filename);
      document.body.appendChild(downloadLink);
      downloadLink.click();
      document.body.removeChild(downloadLink);

      fetchTrainingDataset();
    } catch (err) {
      console.error("Error saving training mask:", err);
      setError(err.message);
    } finally {
      setMaskSaving(false);
    }
  };

  // --- MASK ADDITION & DELETION LOGIC ---

  // Delete a cell (works for both AI-predicted and Manual freehand cells)
  const deleteCell = (tileName, cellId) => {
    setTiles(prevTiles => {
      const tile = prevTiles.find(t => t.tile_name === tileName);
      if (!tile) return prevTiles;
      
      const cellToDelete = tile.cells.find(c => c.id === cellId);
      if (!cellToDelete) return prevTiles;

      const updatedCells = tile.cells.filter(c => c.id !== cellId);
      const updatedTile = {
        ...tile,
        count: updatedCells.length,
        cells: updatedCells
      };

      const newTiles = prevTiles.map(t => t.tile_name === tileName ? updatedTile : t);
      
      // Save to undo stack
      setUndoStack(prev => [{ tileName, cell: cellToDelete }, ...prev.slice(0, 19)]);
      
      recomputeStats(newTiles);
      return newTiles;
    });

    if (selectedCellId === cellId) {
      setSelectedCellId(null);
    }
  };

  // Undo the last deletion
  const undoLastDelete = () => {
    if (undoStack.length === 0) return;
    const [lastAction, ...remainingStack] = undoStack;
    const { tileName, cell } = lastAction;

    setTiles(prevTiles => {
      const tile = prevTiles.find(t => t.tile_name === tileName);
      if (!tile) return prevTiles;

      // Re-insert cell
      const updatedCells = [...tile.cells, cell].sort((a, b) => a.id - b.id);
      const updatedTile = {
        ...tile,
        count: updatedCells.length,
        cells: updatedCells
      };

      const newTiles = prevTiles.map(t => t.tile_name === tileName ? updatedTile : t);
      recomputeStats(newTiles);
      return newTiles;
    });

    setUndoStack(remainingStack);
  };

  // Reset tile back to original AI predictions
  const resetTileToOriginal = (tileName) => {
    const originalCells = originalTilesBackup[tileName];
    if (!originalCells) return;

    setTiles(prevTiles => {
      const newTiles = prevTiles.map(t => {
        if (t.tile_name === tileName) {
          const restoredCells = JSON.parse(JSON.stringify(originalCells));
          return {
            ...t,
            count: restoredCells.length,
            cells: restoredCells
          };
        }
        return t;
      });
      recomputeStats(newTiles);
      return newTiles;
    });
    setSelectedCellId(null);
  };

  // Clear all manual annotations in active tile
  const clearManualMasksInTile = (tileName) => {
    setTiles(prevTiles => {
      const newTiles = prevTiles.map(t => {
        if (t.tile_name === tileName) {
          const aiOnly = t.cells.filter(c => !c.manual);
          return {
            ...t,
            count: aiOnly.length,
            cells: aiOnly
          };
        }
        return t;
      });
      recomputeStats(newTiles);
      return newTiles;
    });
  };

  // Freehand Drawing Event Handlers
  const handleSvgMouseDown = (e) => {
    if (toolMode !== 'freehand' || !activeTile) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 512);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 512);
    setCurrentPath([{ x, y }]);
  };

  const handleSvgMouseMove = (e) => {
    if (toolMode !== 'freehand' || currentPath.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 512);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 512);
    setCurrentPath(prev => [...prev, { x, y }]);
  };

  const handleSvgMouseUp = () => {
    if (toolMode !== 'freehand' || currentPath.length === 0) return;
    if (currentPath.length < 3) {
      setCurrentPath([]);
      return;
    }
    
    const area = calculatePolygonArea(currentPath);
    const perimeter = calculatePolygonPerimeter(currentPath);
    const circularity = calculateCircularity(area, perimeter);
    
    // Ignore accidental clicks / micro-drawings
    if (area < 8) {
       setCurrentPath([]);
       return;
    }
    
    const centroid = calculateCentroid(currentPath);
    const existingIds = activeTile.cells.map(c => c.id);
    const newCellId = existingIds.length > 0 ? Math.max(...existingIds) + 1 : 1;
    
    const newCell = { 
      id: newCellId, 
      area: parseFloat(area.toFixed(1)), 
      circularity: parseFloat(circularity.toFixed(3)), 
      centroid,
      contour: currentPath,
      manual: true 
    };
    
    setTiles(prevTiles => {
      const updatedCells = [...activeTile.cells, newCell];
      const updatedTile = {
        ...activeTile,
        count: updatedCells.length,
        cells: updatedCells
      };
      const newTiles = prevTiles.map(t => t.tile_name === activeTile.tile_name ? updatedTile : t);
      recomputeStats(newTiles);
      return newTiles;
    });
    
    setCurrentPath([]);
    setSelectedCellId(newCellId);
  };

  // Histogram calculation
  let areaData = [];
  let circData = [];
  if (results && results.areas && results.circularities) {
    if (results.areas.length > 0) {
      const minArea = Math.min(...results.areas);
      const maxArea = Math.max(...results.areas);
      const areaStep = (maxArea - minArea) / 10 || 1;
      let aBins = new Array(10).fill(0);
      results.areas.forEach(a => {
        let idx = Math.floor((a - minArea) / areaStep);
        if (idx >= 10) idx = 9;
        aBins[idx]++;
      });
      areaData = aBins.map((count, i) => ({
        name: Math.round(minArea + (i * areaStep)).toString(),
        count
      }));
    }

    if (results.circularities.length > 0) {
      const minCirc = Math.min(...results.circularities);
      const maxCirc = Math.max(...results.circularities);
      const circStep = (maxCirc - minCirc) / 10 || 0.1;
      let cBins = new Array(10).fill(0);
      results.circularities.forEach(c => {
        let idx = Math.floor((c - minCirc) / circStep);
        if (idx >= 10) idx = 9;
        cBins[idx]++;
      });
      circData = cBins.map((count, i) => ({
        name: (minCirc + (i * circStep)).toFixed(2),
        count
      }));
    }
  }

  const handleWheel = (e) => {
    const scaleChange = e.deltaY * -0.001;
    setScale(s => Math.min(Math.max(0.1, s + scaleChange), 5));
  };
  const handlePanDown = (e) => {
    setIsDragging(true);
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };
  const handlePanMove = (e) => {
    if (!isDragging) return;
    setPan({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y });
  };
  const handlePanUp = () => setIsDragging(false);

  // Filtered cells in table
  const displayedCells = activeTile?.cells ? activeTile.cells.filter(c => {
    if (cellFilter === 'ai') return !c.manual;
    if (cellFilter === 'manual') return c.manual;
    return true;
  }) : [];

  // Filtered tiles in library
  const displayedTiles = tiles.filter(t => {
    if (tileFilter === 'detected') return t.count > 0;
    return true;
  });

  return (
    <div className="flex h-screen w-screen bg-gradient-to-br from-[#fcf9fb] to-[#fce7f3] text-[#1a181a] font-sans overflow-hidden p-4 gap-4">
      
      {/* 1. Left Sidebar Navigation */}
      <nav className="w-[260px] bg-white/80 backdrop-blur-md rounded-3xl border border-rose-100 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col justify-between shrink-0 h-full z-10 overflow-hidden">
        <div className="flex flex-col h-full overflow-hidden">
          <div className="p-6 shrink-0 flex items-center justify-between">
            <h1 className="text-xl font-bold tracking-tight text-[#1a181a] flex items-center">
              <Hexagon size={22} className="mr-2 text-[#7b1738]" />
              OCLAST
            </h1>
            <span className="text-[10px] bg-rose-50 text-[#7b1738] font-bold px-2 py-0.5 rounded-full border border-rose-100">
              v2.2
            </span>
          </div>
          
          <div className="flex-1 overflow-y-auto custom-scrollbar px-4 pb-4 space-y-5">
            {/* Ground Truth Training Dataset Counter */}
            <div className="bg-emerald-50/70 border border-emerald-200/80 rounded-2xl p-3 text-xs">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-bold text-emerald-900 flex items-center">
                  <ShieldCheck size={14} className="mr-1.5 text-emerald-600"/> Training Dataset
                </span>
                <span className="bg-emerald-600 text-white font-bold text-[10px] px-2 py-0.5 rounded-full">
                  {trainingDatasetCount} masks
                </span>
              </div>
              <p className="text-[10px] text-emerald-700/80 mb-2 leading-relaxed">
                Approved ground truth binary <code className="bg-emerald-100/60 px-1 py-0.5 rounded text-emerald-900">_mask.tif</code> pairs for retraining.
              </p>
              <button 
                onClick={() => { fetchTrainingDataset(); setShowDatasetModal(true); }}
                className="w-full text-center py-1.5 text-[11px] font-bold text-emerald-800 bg-white hover:bg-emerald-100/60 rounded-xl border border-emerald-200 transition-colors shadow-sm"
              >
                Browse Training Masks
              </button>
            </div>

            {/* Session History */}
            <div>
              <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-3 pl-2">Session History</h3>
              <div className="space-y-3">
                {history.length === 0 ? (
                  <div className="text-xs text-slate-400 italic text-center py-4">No past sessions</div>
                ) : (
                  history.map(session => (
                    <div key={session.id} className="bg-white/80 backdrop-blur-md border border-rose-100 p-3 rounded-2xl shadow-[0_8px_30px_rgba(159,18,57,0.04)] relative group text-xs hover:border-rose-300 transition-colors">
                       <div className="font-bold text-slate-700 truncate pr-6" title={session.filename}>{session.filename}</div>
                       <div className="text-[10px] text-[#7b1738] font-semibold mb-1">{session.model}</div>
                       <div className="flex justify-between text-slate-500 mb-1">
                          <span>{session.cells} cells</span>
                          <span>{session.timestamp}</span>
                       </div>
                       <div className="flex justify-between text-slate-400 text-[10px]">
                          <span>Area: {session.avgArea ? session.avgArea.toFixed(1) : '---'} px²</span>
                          <span>Circ: {session.avgCirc ? session.avgCirc.toFixed(3) : '---'}</span>
                       </div>
                       <button onClick={() => downloadCSV(session.tiles)} className="absolute top-2 right-2 p-1.5 text-slate-400 hover:text-[#7b1738] hover:bg-rose-50 rounded transition-colors opacity-0 group-hover:opacity-100" title="Download CSV">
                         <Download size={14} />
                       </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* Main Container */}
      <div className="flex-1 flex flex-col min-w-0 z-0 gap-4">
        
        {/* Header with Prominent Approve & Export Mask Action */}
        <header className="h-16 bg-white/80 backdrop-blur-md rounded-full border border-rose-100 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex items-center px-6 justify-between shrink-0">
          <div className="flex items-center space-x-4">
            <span className="text-xs font-bold text-slate-500 uppercase">Active Specimen:</span>
            <span className="text-sm font-bold text-[#1a181a] bg-slate-100 px-3 py-1 rounded-md">{filename || 'NONE LOADED'}</span>
          </div>
          
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-3 text-xs text-slate-500">
               <span className="flex items-center"><span className="w-2.5 h-2.5 rounded-full bg-rose-500 inline-block mr-1.5"></span> AI Predicted</span>
               <span className="flex items-center"><span className="w-2.5 h-2.5 rounded-full bg-purple-500 inline-block mr-1.5"></span> Manual Annotated</span>
            </div>

            {/* Approve & Export Training Mask Button */}
            {results && (
              <button 
                onClick={() => { setSavedMaskResult(null); setShowApprovalModal(true); }}
                className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-4 py-2 rounded-full flex items-center shadow-md shadow-emerald-600/20 transition-all hover:scale-[1.02] active:scale-95"
                title="Approve segmentation and generate ground truth .tif mask for model retraining"
              >
                <CheckCircle2 size={15} className="mr-1.5" /> Approve & Export Training Mask (.tif)
              </button>
            )}
          </div>
        </header>

        {/* Content Wrapper */}
        <div className="flex-1 flex gap-4 overflow-hidden">
          
          {/* 2. Control Panel (Left Pane) */}
          <aside className="w-[300px] bg-white/80 backdrop-blur-md rounded-3xl border border-rose-100 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col overflow-hidden shrink-0 custom-scrollbar">
            
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Load Specimen */}
              <div className="border-2 border-dashed border-slate-200 rounded-3xl p-6 text-center bg-slate-50 relative group">
                <input type="file" id="file-upload" className="hidden" accept="image/*" onChange={handleFileChange} />
                <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center">
                  <div className="p-3 bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl mb-4 group-hover:border-rose-300 transition-colors shadow-[0_8px_30px_rgba(159,18,57,0.04)]">
                    <UploadCloud size={24} className="text-slate-400 group-hover:text-[#7b1738] transition-colors" />
                  </div>
                  <h3 className="font-bold text-[#1a181a] text-sm mb-1">Load Microscopy Image</h3>
                  <p className="text-xs text-slate-400">Supports .TIF, .TIFF, .PNG, .JPG</p>
                </label>
                {filename && (
                   <div className="mt-4 pt-4 border-t border-slate-100 flex justify-between items-center">
                      <span className="text-xs font-semibold text-slate-600 truncate max-w-[150px]">{filename}</span>
                      <button onClick={() => { setPreview(null); setFile(null); setResults(null); setTiles([]); setOriginalTilesBackup({}); }} className="text-[10px] bg-slate-200 px-2 py-1 rounded text-slate-600 hover:bg-slate-300">Clear</button>
                   </div>
                )}
              </div>

              {/* Heatmap Overlay */}
              {results?.heatmap && (
                <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl overflow-hidden shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col mb-4">
                  <div className="bg-slate-50 border-b border-slate-100 px-5 py-3">
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Density Heatmap</h3>
                  </div>
                  <div className="p-4 bg-white/80 backdrop-blur-md border border-rose-100 flex justify-center">
                    <img src={results.heatmap} alt="Heatmap" className="w-full h-auto rounded-2xl object-contain border border-slate-100 shadow" />
                  </div>
                </div>
              )}
              
              <div className="pt-4 border-t border-slate-100 mt-auto">
                  <button 
                    onClick={runInference}
                    disabled={loading || !file}
                    className="w-full bg-[#1a181a] hover:bg-black text-white py-3.5 rounded-2xl font-bold text-sm shadow-lg shadow-slate-200 transition-all flex justify-center items-center disabled:opacity-50"
                  >
                    {loading ? <span className="flex items-center"><Activity size={16} className="mr-2 animate-spin"/> Processing...</span> : "Commence Analysis"}
                  </button>
                  {loading && (
                    <div className="mt-4 w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                      <div className="bg-[#7b1738] h-1.5 rounded-full transition-all duration-300" style={{ width: `${progress}%` }}></div>
                    </div>
                  )}
              </div>
            </div>
          </aside>

          {/* 3. Main Workspace Area */}
          <main className="flex-1 flex flex-col min-w-0 overflow-hidden gap-4">
            
            {/* Top: Interactive Canvas */}
            <div className="flex-1 bg-[#e2e8f0] border border-slate-300 rounded-3xl overflow-hidden relative shadow-inner flex items-center justify-center cursor-grab active:cursor-grabbing"
                 onWheel={handleWheel} onMouseDown={handlePanDown} onMouseMove={handlePanMove} onMouseUp={handlePanUp} onMouseLeave={handlePanUp}>
              
              {!preview ? (
                <div className="flex flex-col items-center text-slate-400">
                  <Eye size={48} className="mb-4 opacity-50" />
                  <p className="font-semibold">Canvas Awaiting Specimen</p>
                </div>
              ) : (
                <div style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transition: isDragging ? 'none' : 'transform 0.1s ease-out' }} className="origin-center w-full h-full flex items-center justify-center">
                  <img src={viewHeatmap && results?.heatmap ? results.heatmap : preview} alt="Specimen" className="max-w-none shadow-2xl pointer-events-none" draggable="false" />
                </div>
              )}
              
              <div className="absolute right-4 top-1/2 -translate-y-1/2 flex flex-col space-y-2">
                <button onClick={(e) => { e.stopPropagation(); setScale(s => s + 0.2); }} className="p-2 bg-[#1a181a]/80 text-white rounded-xl shadow hover:bg-slate-700 transition"><ZoomIn size={16}/></button>
                <button onClick={(e) => { e.stopPropagation(); setScale(s => Math.max(0.1, s - 0.2)); }} className="p-2 bg-[#1a181a]/80 text-white rounded-xl shadow hover:bg-slate-700 transition"><ZoomOut size={16}/></button>
                <button onClick={(e) => { e.stopPropagation(); setScale(1); setPan({x:0, y:0}); }} className="p-2 bg-[#1a181a]/80 text-white rounded-xl shadow hover:bg-slate-700 transition" title="Fit to Screen"><Maximize2 size={16}/></button>
                {results?.heatmap && (
                   <button onClick={(e) => { e.stopPropagation(); setViewHeatmap(!viewHeatmap); }} className={`p-2 rounded-xl shadow transition ${viewHeatmap ? 'bg-[#7b1738] text-white' : 'bg-[#1a181a]/80 text-white hover:bg-slate-700'}`} title="Toggle Heatmap"><Layers size={16}/></button>
                )}
              </div>
              
              {loading && <div className="absolute bottom-0 left-0 h-1.5 bg-[#7b1738] transition-all duration-300" style={{ width: `${progress}%` }}></div>}
            </div>

            {/* Middle: Clinical Metrics Blocks */}
            <div className="grid grid-cols-3 gap-4 shrink-0">
              <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl p-5 shadow-[0_8px_30px_rgba(159,18,57,0.04)]">
                <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Total Osteoclasts</h4>
                <div className="flex items-end justify-between">
                  <div>
                    <span className="text-3xl font-bold text-[#1a181a]">{results ? results.total_cells.toLocaleString() : '---'}</span>
                    <span className="text-sm font-semibold text-slate-400 ml-1">cells</span>
                  </div>
                </div>
              </div>
              <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl p-5 shadow-[0_8px_30px_rgba(159,18,57,0.04)]">
                <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Avg. Area</h4>
                <div className="flex items-end justify-between">
                  <div>
                    <span className="text-3xl font-bold text-[#1a181a]">{results ? results.average_size.toFixed(1) : '---'}</span>
                    <span className="text-sm font-semibold text-slate-400 ml-1">px²</span>
                  </div>
                </div>
              </div>
              <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl p-5 shadow-[0_8px_30px_rgba(159,18,57,0.04)]">
                <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Cellular Circularity</h4>
                <div className="flex items-end justify-between">
                  <div>
                    <span className="text-3xl font-bold text-[#1a181a]">{results ? results.average_circularity.toFixed(3) : '---'}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom: Two Morphology Distributions */}
            <div className="grid grid-cols-2 gap-4 h-48 shrink-0">
              <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl p-5 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col h-full">
                <div className="flex justify-between items-center mb-2">
                  <h4 className="text-[10px] font-bold text-[#1a181a] uppercase tracking-wider">Area Distribution (px²)</h4>
                </div>
                <div className="flex-1 w-full min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={areaData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                      <Tooltip cursor={{fill: 'rgba(0,0,0,0.02)'}} contentStyle={{borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '11px'}} />
                      <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                        {areaData.map((entry, index) => {
                           const maxVal = Math.max(...areaData.map(d => d.count));
                           return <Cell key={`cell-${index}`} fill={entry.count === maxVal ? '#7b1738' : '#cbd5e1'} />;
                        })}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-3xl p-5 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col h-full">
                <div className="flex justify-between items-center mb-2">
                  <h4 className="text-[10px] font-bold text-[#1a181a] uppercase tracking-wider">Circularity Distribution</h4>
                </div>
                <div className="flex-1 w-full min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={circData} margin={{ top: 5, right: 10, left: -25, bottom: 0 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                      <Tooltip cursor={{fill: 'rgba(0,0,0,0.02)'}} contentStyle={{borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '11px'}} />
                      <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                        {circData.map((entry, index) => {
                           const maxVal = Math.max(...circData.map(d => d.count));
                           return <Cell key={`cell-${index}`} fill={entry.count === maxVal ? '#7b1738' : '#cbd5e1'} />;
                        })}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

          </main>

          {/* 4. Right Edge: Extraction Tile Library */}
          <aside className="w-[330px] bg-white/80 backdrop-blur-xl rounded-3xl border border-rose-100 shadow-[0_8px_30px_rgba(159,18,57,0.04)] flex flex-col shrink-0 overflow-hidden">
            <div className="flex-1 flex flex-col overflow-hidden bg-slate-50/30">
               <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-white/80 backdrop-blur-md z-10">
                  <div>
                    <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">Extraction Library</h3>
                    <div className="flex space-x-2 mt-1">
                       <button onClick={() => setTileFilter('detected')} className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${tileFilter === 'detected' ? 'bg-[#7b1738] text-white' : 'text-slate-500 hover:bg-slate-100'}`}>
                         Detections ({tiles.filter(t => t.count > 0).length})
                       </button>
                       <button onClick={() => setTileFilter('all')} className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${tileFilter === 'all' ? 'bg-[#7b1738] text-white' : 'text-slate-500 hover:bg-slate-100'}`}>
                         All ({tiles.length})
                       </button>
                    </div>
                  </div>
                  {results && (
                     <div className="flex space-x-1.5">
                       <button onClick={() => downloadCSV(tiles)} className="text-[11px] font-bold text-slate-700 flex items-center hover:bg-slate-100 transition-colors bg-white px-2 py-1 rounded-lg border border-slate-200" title="Export tabular data">
                          <Download size={11} className="mr-1" /> CSV
                       </button>
                       <button onClick={() => { setSavedMaskResult(null); setShowApprovalModal(true); }} className="text-[11px] font-bold text-emerald-800 flex items-center bg-emerald-50 hover:bg-emerald-100 px-2 py-1 rounded-lg border border-emerald-200 transition-colors" title="Export .TIF binary mask">
                          <CheckCircle2 size={11} className="mr-1 text-emerald-600" /> Mask
                       </button>
                     </div>
                  )}
               </div>
               
               <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
                  {displayedTiles.length === 0 ? (
                     <div className="text-xs text-slate-400 italic text-center py-8">Library empty</div>
                  ) : (
                     <div className="grid grid-cols-2 gap-3">
                        {displayedTiles.map((tile, i) => (
                           <div 
                              key={i} 
                              onClick={() => { 
                                setSelectedTileName(tile.tile_name); 
                                setToolMode('inspect'); 
                                setCurrentPath([]); 
                                setSelectedCellId(null);
                              }} 
                              className="bg-white/80 backdrop-blur-md border border-rose-100 rounded-2xl p-2 cursor-pointer hover:border-rose-300 hover:shadow-md transition-all group"
                           >
                              <div className="aspect-square bg-slate-100 rounded-xl overflow-hidden relative mb-2">
                                 {/* Display clean raw image or fallback mask */}
                                 <img 
                                   src={showConfidence && tile.confidence ? tile.confidence : (tile.raw || tile.mask)} 
                                   alt={`Tile ${i}`} 
                                   className="w-full h-full object-cover" 
                                 />
                                 
                                 {/* Dynamic SVG overlay matching currently active cells (hides deleted, shows added) */}
                                 {(!showConfidence || !tile.confidence) && tile.cells && tile.cells.length > 0 && (
                                   <svg viewBox="0 0 512 512" className="absolute inset-0 w-full h-full pointer-events-none">
                                     {tile.cells.map((cell) => {
                                       if (!cell.contour || cell.contour.length < 3) return null;
                                       return (
                                         <polygon 
                                           key={cell.id} 
                                           points={cell.contour.map(p => `${p.x},${p.y}`).join(' ')} 
                                           fill={cell.manual ? "rgba(168, 85, 247, 0.45)" : "rgba(225, 29, 72, 0.35)"} 
                                           stroke={cell.manual ? "#9333ea" : "#be123c"} 
                                           strokeWidth="4" 
                                         />
                                       );
                                     })}
                                   </svg>
                                 )}
                              </div>
                              <div className="text-[10px] font-bold text-slate-700 mb-0.5 truncate">{tile.tile_name}</div>
                              <div className="flex justify-between items-center text-[9px] font-semibold text-[#7b1738]">
                                <span>{tile.count} cells</span>
                                {tile.cells && tile.cells.some(c => c.manual) && (
                                  <span className="text-purple-600 bg-purple-50 px-1 rounded text-[8px]">Edited</span>
                                )}
                              </div>
                           </div>
                        ))}
                     </div>
                  )}
               </div>
               
               {tiles.length > 0 && (
                  <div className="p-3 bg-white/80 backdrop-blur-md border-t border-slate-100 flex items-center justify-between">
                     <span className="text-xs font-bold text-slate-600">Saliency Heatmap</span>
                     <button onClick={() => setShowConfidence(!showConfidence)} className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${showConfidence ? 'bg-[#7b1738]' : 'bg-slate-300'}`}>
                        <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${showConfidence ? 'translate-x-5' : 'translate-x-1'}`} />
                     </button>
                  </div>
               )}
            </div>
          </aside>
        </div>
      </div>

      {/* --- APPROVE & EXPORT TRAINING MASK MODAL --- */}
      {showApprovalModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-xl overflow-hidden flex flex-col border border-slate-200 animate-in zoom-in-95 duration-200">
            
            {/* Header */}
            <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/70">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 bg-emerald-100 text-emerald-700 rounded-2xl">
                  <ShieldCheck size={22} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Approve & Export Training Mask</h3>
                  <p className="text-xs text-slate-500">Converts verified segmentation into binary .tif for retraining</p>
                </div>
              </div>
              <button 
                onClick={() => setShowApprovalModal(false)}
                className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-full transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-4">
              
              {!savedMaskResult ? (
                <>
                  <div className="bg-slate-50 rounded-2xl p-4 border border-slate-200/80 space-y-3 text-xs">
                    <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Source Specimen:</span>
                      <span className="font-bold text-slate-800 font-mono">{filename}</span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Generated Mask File:</span>
                      <span className="font-bold text-emerald-800 font-mono bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        {filename ? `${filename.replace(/\.[^/.]+$/, "")}_mask.tif` : 'specimen_mask.tif'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Target Dimensions:</span>
                      <span className="font-semibold text-slate-700">
                        {results?.orig_width || 'Auto'} × {results?.orig_height || 'Auto'} px
                      </span>
                    </div>
                    <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                      <span className="text-slate-500 font-medium">Approved Osteoclasts:</span>
                      <span className="font-bold text-[#7b1738]">
                        {results?.total_cells || 0} cells
                      </span>
                    </div>
                    <div className="flex justify-between items-start py-1">
                      <span className="text-slate-500 font-medium">Local Storage:</span>
                      <span className="font-mono text-[11px] text-slate-600 text-right max-w-[280px] break-all">
                        training_data/masks/
                      </span>
                    </div>
                  </div>

                  <div className="bg-amber-50 border border-amber-200 rounded-2xl p-3.5 flex items-start space-x-3 text-xs text-amber-900">
                    <Info size={16} className="text-amber-600 shrink-0 mt-0.5" />
                    <p className="leading-relaxed">
                      By approving, a 1-channel binary <strong>.tif</strong> mask (0 = background, 255 = osteoclast cells) will be generated, saved locally to <code className="bg-amber-100/70 px-1 py-0.5 rounded">training_data/masks/</code>, and automatically downloaded to your machine.
                    </p>
                  </div>
                </>
              ) : (
                /* Success View with Binary Mask Preview */
                <div className="space-y-4">
                  <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-4 flex items-center space-x-3 text-xs text-emerald-900">
                    <CheckCircle2 size={24} className="text-emerald-600 shrink-0" />
                    <div>
                      <h4 className="font-bold text-sm text-emerald-950">Ground Truth Mask Successfully Saved!</h4>
                      <p className="text-emerald-800 text-[11px] mt-0.5">
                        File <span className="font-mono font-bold">{savedMaskResult.mask_filename}</span> was saved to local disk and downloaded to your computer.
                      </p>
                    </div>
                  </div>

                  {savedMaskResult.preview && (
                    <div className="border border-slate-200 rounded-2xl overflow-hidden bg-black flex flex-col items-center">
                      <div className="w-full bg-slate-900 px-4 py-2 flex justify-between items-center text-[10px] text-slate-400">
                        <span>Binary Mask Preview (0/255)</span>
                        <span>{savedMaskResult.total_cells} segmented cells</span>
                      </div>
                      <img 
                        src={savedMaskResult.preview} 
                        alt="Binary Mask" 
                        className="w-full max-h-[220px] object-contain p-2"
                      />
                    </div>
                  )}

                  <div className="bg-slate-50 rounded-2xl p-3 text-xs space-y-1 text-slate-600 font-mono text-[11px] break-all border border-slate-200">
                    <div><strong>Mask Location:</strong> {savedMaskResult.mask_path}</div>
                    {savedMaskResult.image_path && (
                      <div><strong>Paired Image:</strong> {savedMaskResult.image_path}</div>
                    )}
                  </div>
                </div>
              )}

            </div>

            {/* Modal Footer */}
            <div className="p-6 border-t border-slate-100 bg-slate-50/50 flex justify-end space-x-3">
              {!savedMaskResult ? (
                <>
                  <button 
                    onClick={() => setShowApprovalModal(false)}
                    className="px-4 py-2.5 text-xs font-bold text-slate-600 hover:bg-slate-100 rounded-2xl transition"
                  >
                    Continue Reviewing
                  </button>
                  <button 
                    onClick={handleApproveAndSaveMask}
                    disabled={maskSaving}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-5 py-2.5 rounded-2xl flex items-center shadow-lg shadow-emerald-600/20 transition disabled:opacity-50"
                  >
                    {maskSaving ? (
                      <span className="flex items-center"><Activity size={14} className="mr-2 animate-spin"/> Generating .TIF...</span>
                    ) : (
                      <span className="flex items-center"><FileCheck size={14} className="mr-1.5" /> Approve & Save Mask</span>
                    )}
                  </button>
                </>
              ) : (
                <button 
                  onClick={() => setShowApprovalModal(false)}
                  className="bg-slate-900 hover:bg-black text-white text-xs font-bold px-6 py-2.5 rounded-2xl transition"
                >
                  Done
                </button>
              )}
            </div>

          </div>
        </div>
      )}

      {/* --- TRAINING DATASET BROWSER MODAL --- */}
      {showDatasetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col border border-slate-200 max-h-[85vh]">
            <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/70">
              <div className="flex items-center space-x-3">
                <div className="p-2.5 bg-emerald-100 text-emerald-700 rounded-2xl">
                  <HardDrive size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900">Training Ground Truth Dataset</h3>
                  <p className="text-xs text-slate-500">Collected binary masks in <code className="bg-slate-200/70 px-1 py-0.5 rounded font-mono">training_data/masks/</code></p>
                </div>
              </div>
              <button 
                onClick={() => setShowDatasetModal(false)}
                className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-full transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
              {datasetList.length === 0 ? (
                <div className="text-center py-12 text-slate-400 text-xs italic">
                  No approved masks in training dataset yet.<br/>
                  Analyze an image and click <strong>"Approve & Export Training Mask"</strong> to add samples.
                </div>
              ) : (
                <div className="space-y-3">
                  {datasetList.map((item, idx) => (
                    <div key={idx} className="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-xs flex justify-between items-center hover:border-emerald-300 transition">
                      <div className="space-y-1">
                        <div className="font-bold text-slate-800 font-mono">{item.mask_file}</div>
                        <div className="text-[11px] text-slate-500">
                          Source: <span className="font-semibold text-slate-700">{item.original_filename}</span> • {item.total_cells} cells ({item.manual_cells} manual, {item.ai_cells} AI)
                        </div>
                        <div className="text-[10px] text-slate-400">
                          Dimensions: {item.dimensions ? `${item.dimensions[0]}×${item.dimensions[1]}` : '---'} • Saved: {item.timestamp}
                        </div>
                      </div>
                      <a 
                        href={`http://localhost:8000/download-mask/${item.mask_file.split('/').pop()}`}
                        download
                        className="bg-white hover:bg-emerald-50 text-emerald-800 border border-emerald-200 px-3 py-1.5 rounded-xl font-bold text-xs flex items-center shadow-sm transition"
                      >
                        <Download size={13} className="mr-1" /> Re-download
                      </a>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50/50 flex justify-between items-center text-xs text-slate-500">
              <span>Directory: <strong className="font-mono text-slate-700">./training_data/</strong></span>
              <button 
                onClick={() => setShowDatasetModal(false)}
                className="bg-slate-900 hover:bg-black text-white text-xs font-bold px-4 py-2 rounded-xl transition"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* --- INTERACTIVE TILE INSPECTION & MASK EDITING MODAL --- */}
      {activeTile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-5xl overflow-hidden flex max-h-[90vh] border border-slate-200">
            
            {/* Modal Image Left Side */}
            <div className="w-7/12 bg-slate-100 p-6 flex flex-col relative border-r border-slate-200">
              
              {/* Top Action Toolbar */}
              <div className="flex items-center justify-between mb-4 z-20">
                 {/* Mode Selection */}
                 <div className="flex bg-white/90 backdrop-blur-md rounded-2xl shadow-sm border border-slate-200 p-1">
                    <button 
                      onClick={() => { setToolMode('inspect'); setCurrentPath([]); }} 
                      className={`px-3 py-1.5 text-xs font-bold rounded-xl flex items-center transition-all ${toolMode === 'inspect' ? 'bg-[#1a181a] text-white shadow-sm' : 'text-slate-600 hover:bg-slate-100'}`}
                      title="Inspect and select individual osteoclasts"
                    >
                      <MousePointer2 size={13} className="mr-1.5"/> Inspect
                    </button>
                    
                    <button 
                      onClick={() => { setToolMode('freehand'); setCurrentPath([]); setViewMode('vector'); }} 
                      className={`px-3 py-1.5 text-xs font-bold rounded-xl flex items-center transition-all ${toolMode === 'freehand' ? 'bg-purple-600 text-white shadow-sm' : 'text-purple-700 hover:bg-purple-50'}`}
                      title="Freehand draw to add a mask for a missed osteoclast"
                    >
                      <Edit3 size={13} className="mr-1.5"/> Add Mask (Freehand)
                    </button>
                    
                    <button 
                      onClick={() => { setToolMode('eraser'); setCurrentPath([]); setViewMode('vector'); }} 
                      className={`px-3 py-1.5 text-xs font-bold rounded-xl flex items-center transition-all ${toolMode === 'eraser' ? 'bg-rose-600 text-white shadow-sm' : 'text-rose-700 hover:bg-rose-50'}`}
                      title="Click directly on any AI or manual mask to delete it"
                    >
                      <Eraser size={13} className="mr-1.5"/> Eraser (Click to Delete)
                    </button>
                 </div>

                 {/* Layer View Options */}
                 <div className="flex bg-white/90 backdrop-blur-md rounded-2xl shadow-sm border border-slate-200 p-1 text-[11px] font-bold">
                    <button 
                      onClick={() => setViewMode('vector')} 
                      className={`px-2.5 py-1 rounded-xl transition-all ${viewMode === 'vector' ? 'bg-[#7b1738] text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                      title="Clean tissue image with interactive vector masks"
                    >
                      Vector
                    </button>
                    <button 
                      onClick={() => setViewMode('saliency')} 
                      className={`px-2.5 py-1 rounded-xl transition-all ${viewMode === 'saliency' ? 'bg-[#7b1738] text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                      title="Confidence / Saliency heatmap"
                    >
                      Heatmap
                    </button>
                    <button 
                      onClick={() => setViewMode('burned')} 
                      className={`px-2.5 py-1 rounded-xl transition-all ${viewMode === 'burned' ? 'bg-[#7b1738] text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                      title="Original static AI overlay"
                    >
                      Burned
                    </button>
                 </div>
              </div>

              {/* The Interactive Canvas Area */}
              <div className="relative aspect-square w-full flex-1 flex items-center justify-center rounded-2xl overflow-hidden border border-slate-300 bg-black/5 select-none">
                
                {/* Background Base Tile Image */}
                <img 
                  src={
                    viewMode === 'saliency' && activeTile.confidence ? activeTile.confidence :
                    viewMode === 'burned' ? activeTile.mask :
                    (activeTile.raw || activeTile.mask)
                  } 
                  alt="Tile detail" 
                  className="absolute inset-0 w-full h-full object-contain pointer-events-none" 
                />

                {/* SVG Layer for Drawing, Selecting, and Erasing Masks */}
                <svg 
                  ref={svgRef}
                  viewBox="0 0 512 512" 
                  className={`absolute inset-0 w-full h-full ${
                    toolMode === 'freehand' ? 'cursor-crosshair' : 
                    toolMode === 'eraser' ? 'cursor-pointer' : 'cursor-default'
                  }`}
                  onMouseDown={handleSvgMouseDown}
                  onMouseMove={handleSvgMouseMove}
                  onMouseUp={handleSvgMouseUp}
                  onMouseLeave={handleSvgMouseUp}
                >
                  {/* Render All Active Cell Polygons */}
                  {viewMode === 'vector' && activeTile.cells.map((cell) => {
                    const isHovered = hoveredCellId === cell.id;
                    const isSelected = selectedCellId === cell.id;
                    const isEraserTarget = toolMode === 'eraser' && isHovered;

                    if (!cell.contour || cell.contour.length < 3) return null;

                    const cx = cell.centroid ? cell.centroid[0] : 256;
                    const cy = cell.centroid ? cell.centroid[1] : 256;

                    return (
                      <g key={cell.id} className="transition-opacity">
                        <polygon 
                          points={cell.contour.map(p => `${p.x},${p.y}`).join(' ')}
                          fill={
                            isEraserTarget ? "rgba(239, 68, 68, 0.55)" :
                            isSelected ? "rgba(244, 63, 94, 0.45)" :
                            cell.manual ? "rgba(168, 85, 247, 0.38)" : "rgba(225, 29, 72, 0.32)"
                          }
                          stroke={
                            isEraserTarget ? "#ef4444" :
                            isSelected ? "#f43f5e" :
                            isHovered ? "#000000" :
                            cell.manual ? "#9333ea" : "#be123c"
                          }
                          strokeWidth={isHovered || isSelected ? "3.5" : cell.manual ? "2.5" : "2"}
                          strokeDasharray={cell.manual ? "5 2" : "none"}
                          className="cursor-pointer transition-colors"
                          onMouseEnter={() => setHoveredCellId(cell.id)}
                          onMouseLeave={() => setHoveredCellId(null)}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (toolMode === 'eraser') {
                              deleteCell(activeTile.tile_name, cell.id);
                            } else {
                              setSelectedCellId(cell.id);
                            }
                          }}
                        />

                        {/* ID Number Tag Badge */}
                        {showLabels && (
                          <g 
                            transform={`translate(${cx}, ${cy})`} 
                            className="pointer-events-none select-none"
                          >
                            <circle 
                              r="10" 
                              fill={cell.manual ? "#9333ea" : "#be123c"} 
                              stroke="#ffffff" 
                              strokeWidth="1.5" 
                              opacity="0.9"
                            />
                            <text 
                              y="3" 
                              textAnchor="middle" 
                              fill="#ffffff" 
                              fontSize="8" 
                              fontWeight="bold" 
                              fontFamily="sans-serif"
                            >
                              {cell.id}
                            </text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                  
                  {/* Real-time Freehand Drawing Stroke */}
                  {toolMode === 'freehand' && currentPath.length > 0 && (
                    <polyline 
                      points={currentPath.map(p => `${p.x},${p.y}`).join(' ')}
                      fill="none" 
                      stroke="#ec4899" 
                      strokeWidth="3.5" 
                      strokeDasharray="4"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )}
                </svg>

                {/* Helpful Mode Prompt Banner */}
                <div className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-slate-900/85 backdrop-blur-md text-white text-[11px] font-semibold px-4 py-1.5 rounded-full pointer-events-none flex items-center shadow-lg">
                  {toolMode === 'freehand' && (
                    <span className="flex items-center text-purple-200">
                      <Edit3 size={13} className="mr-1.5 text-purple-400" />
                      Click and drag freely to outline a missed osteoclast
                    </span>
                  )}
                  {toolMode === 'eraser' && (
                    <span className="flex items-center text-rose-200">
                      <Eraser size={13} className="mr-1.5 text-rose-400" />
                      Click any mask (AI or manual) on the image to delete it
                    </span>
                  )}
                  {toolMode === 'inspect' && (
                    <span className="flex items-center text-slate-300">
                      <MousePointer2 size={13} className="mr-1.5 text-slate-400" />
                      Hover or click cells to inspect details or delete via table
                    </span>
                  )}
                </div>
              </div>

              {/* Bottom Controls */}
              <div className="flex justify-between items-center mt-3 pt-3 border-t border-slate-200 text-xs text-slate-600">
                 <div className="flex items-center space-x-4">
                    <label className="flex items-center cursor-pointer select-none">
                       <input 
                         type="checkbox" 
                         checked={showLabels} 
                         onChange={(e) => setShowLabels(e.target.checked)} 
                         className="rounded text-rose-600 mr-1.5"
                       />
                       Show Cell ID Tags
                    </label>
                 </div>

                 {undoStack.length > 0 && (
                   <button 
                     onClick={undoLastDelete} 
                     className="flex items-center text-xs font-bold text-slate-700 bg-white hover:bg-slate-50 px-3 py-1 rounded-xl border border-slate-300 shadow-sm transition"
                     title="Restore last deleted cell"
                   >
                     <RotateCcw size={12} className="mr-1.5 text-slate-500"/> Undo Delete ({undoStack.length})
                   </button>
                 )}
              </div>
            </div>
            
            {/* Modal Table Right Side */}
            <div className="w-5/12 flex flex-col bg-white">
              
              {/* Header */}
              <div className="p-5 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                <div>
                  <h3 className="text-base font-bold text-[#1a181a] flex items-center">
                    {activeTile.tile_name}
                  </h3>
                  <div className="flex items-center space-x-2 mt-1">
                    <span className="text-xs font-bold text-[#7b1738] bg-rose-50 px-2 py-0.5 rounded-md border border-rose-100">
                      {activeTile.count} active osteoclasts
                    </span>
                    <span className="text-[10px] text-slate-400">
                      ({activeTile.cells.filter(c => !c.manual).length} AI, {activeTile.cells.filter(c => c.manual).length} Manual)
                    </span>
                  </div>
                </div>
                <button 
                  onClick={() => { 
                    setSelectedTileName(null); 
                    setToolMode('inspect'); 
                    setCurrentPath([]); 
                    setSelectedCellId(null);
                  }} 
                  className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-200 rounded-full transition-colors"
                >
                  <X size={20} />
                </button>
              </div>

              {/* Filter Tabs & Bulk Actions */}
              <div className="px-5 py-2.5 border-b border-slate-100 flex items-center justify-between bg-white text-xs">
                 <div className="flex space-x-1">
                    <button 
                      onClick={() => setCellFilter('all')} 
                      className={`px-2.5 py-1 rounded-lg font-bold text-[11px] ${cellFilter === 'all' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      All ({activeTile.cells.length})
                    </button>
                    <button 
                      onClick={() => setCellFilter('ai')} 
                      className={`px-2.5 py-1 rounded-lg font-bold text-[11px] ${cellFilter === 'ai' ? 'bg-rose-100 text-rose-800' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      AI ({activeTile.cells.filter(c => !c.manual).length})
                    </button>
                    <button 
                      onClick={() => setCellFilter('manual')} 
                      className={`px-2.5 py-1 rounded-lg font-bold text-[11px] ${cellFilter === 'manual' ? 'bg-purple-100 text-purple-800' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      Manual ({activeTile.cells.filter(c => c.manual).length})
                    </button>
                 </div>

                 {/* Reset original AI button */}
                 <div className="flex space-x-2">
                   {activeTile.cells.some(c => c.manual) && (
                     <button 
                       onClick={() => clearManualMasksInTile(activeTile.tile_name)} 
                       className="text-[10px] text-purple-600 hover:text-purple-800 font-bold"
                       title="Remove all manual annotations from this tile"
                     >
                       Clear Manual
                     </button>
                   )}
                   <button 
                     onClick={() => resetTileToOriginal(activeTile.tile_name)} 
                     className="text-[10px] text-slate-500 hover:text-rose-700 font-bold flex items-center"
                     title="Restore original computer predicted masks"
                   >
                     <RefreshCw size={10} className="mr-1"/> Reset AI
                   </button>
                 </div>
              </div>

              {/* Selected Cell Quick Card */}
              {selectedCellId && activeTile.cells.find(c => c.id === selectedCellId) && (
                <div className="bg-rose-50/60 border-b border-rose-100 px-5 py-3 flex items-center justify-between">
                   {(() => {
                     const cell = activeTile.cells.find(c => c.id === selectedCellId);
                     return (
                       <>
                         <div>
                            <div className="flex items-center space-x-2">
                               <span className="font-bold text-sm text-[#7b1738]">Cell #{cell.id}</span>
                               <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${cell.manual ? 'bg-purple-200 text-purple-800' : 'bg-rose-200 text-rose-800'}`}>
                                 {cell.manual ? 'Manual Freehand' : 'AI Prediction'}
                               </span>
                            </div>
                            <div className="text-[11px] text-slate-600 mt-0.5">
                               Area: <strong className="text-slate-800">{cell.area.toFixed(1)} px²</strong> • Circ: <strong className="text-slate-800">{cell.circularity.toFixed(3)}</strong>
                            </div>
                         </div>
                         <button 
                           onClick={() => deleteCell(activeTile.tile_name, cell.id)}
                           className="bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold px-3 py-1.5 rounded-xl flex items-center shadow-sm transition"
                           title="Delete this mask"
                         >
                           <Trash2 size={13} className="mr-1"/> Delete Mask
                         </button>
                       </>
                     );
                   })()}
                </div>
              )}
              
              {/* Cell Table List */}
              <div className="flex-1 overflow-y-auto custom-scrollbar">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 sticky top-0 border-b border-slate-100 z-10 text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                    <tr>
                      <th className="px-4 py-2.5">ID</th>
                      <th className="px-3 py-2.5">Type</th>
                      <th className="px-3 py-2.5">Area (px²)</th>
                      <th className="px-3 py-2.5">Circularity</th>
                      <th className="px-4 py-2.5 text-right">Delete</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {displayedCells.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="text-center py-8 text-xs text-slate-400 italic">
                          No cells match current filter
                        </td>
                      </tr>
                    ) : (
                      displayedCells.map((cell) => {
                        const isHovered = hoveredCellId === cell.id;
                        const isSelected = selectedCellId === cell.id;
                        return (
                          <tr 
                            key={cell.id} 
                            onMouseEnter={() => setHoveredCellId(cell.id)}
                            onMouseLeave={() => setHoveredCellId(null)}
                            onClick={() => setSelectedCellId(cell.id)}
                            className={`cursor-pointer transition-colors ${
                              isSelected ? 'bg-rose-50/70' : 
                              isHovered ? 'bg-slate-50' : ''
                            }`}
                          >
                            <td className="px-4 py-2.5 font-mono font-bold text-[#7b1738]">
                              #{cell.id}
                            </td>
                            <td className="px-3 py-2.5 font-semibold">
                              {cell.manual ? (
                                <span className="text-purple-700 bg-purple-50 px-2 py-0.5 rounded-full text-[9px] font-bold border border-purple-100">
                                  Manual
                                </span>
                              ) : (
                                <span className="text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full text-[9px] font-bold">
                                  AI
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2.5 font-semibold text-slate-700">
                              {cell.area.toFixed(1)}
                            </td>
                            <td className="px-3 py-2.5 font-semibold text-slate-700">
                              {cell.circularity.toFixed(3)}
                            </td>
                            <td className="px-4 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                              <button 
                                onClick={() => deleteCell(activeTile.tile_name, cell.id)}
                                className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                                title={`Delete ${cell.manual ? 'freehand' : 'computer-predicted'} mask #${cell.id}`}
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
