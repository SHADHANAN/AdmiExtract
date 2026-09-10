import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'

export const Settings: React.FC = () => {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Configure dashboard variables, system preferences, and model confidence thresholds."
      />

      <div className="grid gap-6 max-w-2xl">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>AI Document Extraction Thresholds</CardTitle>
            <CardDescription>Adjust the sensitivity of classification and key field extractions.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Input
              label="Passport OCR Confidence Threshold (%)"
              type="number"
              defaultValue={85}
              helperText="Flags extractions below this value for manual counselor check"
            />
            <Input
              label="Transcript Grade Parsing Threshold (%)"
              type="number"
              defaultValue={90}
              helperText="Minimum confidence to auto-approve student transcripts"
            />
            <Button variant="primary" className="mt-2">
              Save Preferences
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
