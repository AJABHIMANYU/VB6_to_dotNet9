import React, { useState } from 'react';
import axios from 'axios';
import { Container, Row, Col, Alert, Spinner, Button } from 'react-bootstrap';
import 'bootstrap/dist/css/bootstrap.min.css';
import './App.css';

function App() {
  const [analysisId, setAnalysisId] = useState('');
  const [analysisResult, setAnalysisResult] = useState(null);
  const [migrationResult, setMigrationResult] = useState(null);
  const [error, setError] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isMigrating, setIsMigrating] = useState(false);
  
  // --- THIS LINE WAS MISSING ---
  const [downloadUrl, setDownloadUrl] = useState('');
  // --- END OF FIX ---

  const apiBaseUrl = 'http://localhost:8000'; // Your backend URL

  const handleAnalyze = async (e) => {
    e.preventDefault();
    setError('');
    setAnalysisResult(null);
    setMigrationResult(null);
    setDownloadUrl(''); // Also reset download URL when starting a new analysis
    setIsAnalyzing(true);
    
    const projectPath = e.target.projectPath.value;

    try {
      const payload = {
        vb6_project_path: projectPath
      };
      const response = await axios.post(`${apiBaseUrl}/analyze`, payload);
      setAnalysisResult(response.data);
      if (response.data.analysis_id) {
        setAnalysisId(response.data.analysis_id);
      }
    } catch (err) {
      const errorMessage = err.response?.data?.detail ? JSON.stringify(err.response.data.detail) : err.message;
      setError('Analysis failed: ' + errorMessage);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleMigrate = async (e) => {
    e.preventDefault();
    setError('');
    setMigrationResult(null);
    setDownloadUrl(''); // Reset download URL on new migration attempt
    setIsMigrating(true);
    
    const id = e.target.analysisId.value;
    const modifiedArchText = e.target.modifiedArch.value.trim();
    let modifiedArchPayload = null;

    if (modifiedArchText) {
      try {
        modifiedArchPayload = JSON.parse(modifiedArchText);
      } catch (jsonErr) {
        setError('Migration failed: The "Modified Architecture" is not valid JSON. Please correct it or leave it empty.');
        setIsMigrating(false);
        return;
      }
    }

    try {
      const payload = {
        analysis_id: id,
        modified_architecture: modifiedArchPayload,
      };

      const response = await axios.post(`${apiBaseUrl}/migrate`, payload);
      setMigrationResult(response.data);

      // This part now works correctly because setDownloadUrl is defined
      if (response.data.zip_path) {
        const url = `${apiBaseUrl}/static/${response.data.zip_path}`;
        setDownloadUrl(url);
        console.log("Download URL created:", url);
      }

    } catch (err) {
      const errorMessage = err.response?.data?.detail ? JSON.stringify(err.response.data.detail) : err.message;
      setError('Migration failed: ' + errorMessage);
    } finally {
      setIsMigrating(false);
    }
  };

  return (
    <Container className="mt-5">
      <h1 className="text-center mb-4">VB6 to .NET Migration Tool</h1>
      {error && <Alert variant="danger">{error}</Alert>}

      <Row className="mt-4">
        {/* Analysis Column */}
        <Col md={6} className="card-column">
          <div className="card p-4">
            <h2 className="card-title">1. Analyze VB6 Project</h2>
            <form onSubmit={handleAnalyze}>
              <div className="mb-3">
                <label htmlFor="projectPath" className="form-label">Git Repo URL or Local File Path:</label>
                <input 
                  type="text" 
                  name="projectPath" 
                  id="projectPath"
                  className="form-control" 
                  placeholder="e.g., https://github.com/user/repo.git"
                  required 
                />
              </div>
              <Button type="submit" variant="primary" disabled={isAnalyzing}>
                {isAnalyzing ? (
                  <>
                    <Spinner as="span" animation="border" size="sm" role="status" aria-hidden="true" />
                    {' '}Analyzing...
                  </>
                ) : (
                  'Analyze'
                )}
              </Button>
            </form>
            {analysisResult && (
              <div className="mt-4 result-box">
                <h4>Analysis Result</h4>
                <pre>{JSON.stringify(analysisResult, null, 2)}</pre>
              </div>
            )}
          </div>
        </Col>

        {/* Migration Column */}
        <Col md={6} className="card-column">
          <div className="card p-4">
            <h2 className="card-title">2. Migrate Project</h2>
            <form onSubmit={handleMigrate}>
              <div className="mb-3">
                <label htmlFor="analysisId" className="form-label">Analysis ID:</label>
                <input 
                  type="text" 
                  name="analysisId"
                  id="analysisId"
                  value={analysisId}
                  onChange={(e) => setAnalysisId(e.target.value)}
                  className="form-control" 
                  required 
                  readOnly
                />
              </div>
              <div className="mb-3">
                <label htmlFor="modifiedArch" className="form-label">Modified Architecture JSON (Optional):</label>
                <textarea 
                  name="modifiedArch" 
                  id="modifiedArch"
                  className="form-control" 
                  rows="5"
                  placeholder="Leave empty to use the proposed architecture."
                ></textarea>
              </div>
              <Button type="submit" variant="success" disabled={!analysisId || isMigrating}>
                {isMigrating ? (
                  <>
                    <Spinner as="span" animation="border" size="sm" role="status" aria-hidden="true" />
                    {' '}Migrating...
                  </>
                ) : (
                  'Migrate'
                )}
              </Button>
            </form>
            {migrationResult && (
              <div className="mt-4 result-box">
                <h4>Migration Result</h4>
                <Alert variant="success">
                  <strong>Status:</strong> {migrationResult.status}
                </Alert>
                {downloadUrl && (
                  <div>
                    <a href={downloadUrl} className="btn btn-lg btn-success" download>
                      Download Migrated Project (.zip)
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        </Col>
      </Row>
    </Container>
  );
}

export default App;