import React from 'react'
import { PageHeader } from '../components/PageHeader'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card'
import { Link as LinkIcon, Plus, Calendar, Eye, Users } from 'lucide-react'
import { Button } from '../components/ui/Button'

export const UploadLinks: React.FC = () => {
  const links = [
    {
      id: 'lnk_1',
      title: 'UK September 2027 Intake',
      description: 'Public portal for UK admissions students to upload copies of passports and transcripts.',
      token: 'uk-sept-2027-token',
      submission_count: 84,
      max_submissions: 100,
      expires_at: '2027-08-31',
      is_active: true,
    },
    {
      id: 'lnk_2',
      title: 'USA Fall 2027 Intake',
      description: 'Public link for USA department applicant submissions.',
      token: 'usa-fall-2027-token',
      submission_count: 142,
      max_submissions: 200,
      expires_at: '2027-07-15',
      is_active: true,
    },
    {
      id: 'lnk_3',
      title: 'Australia Spring 2027 Intake',
      description: 'Link for Australian regional applicant documents.',
      token: 'aus-spring-2027-token',
      submission_count: 9,
      max_submissions: 50,
      expires_at: '2026-12-15',
      is_active: false,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Upload Links"
        description="Generate tokenized, secure links to allow students to submit admission files without accounts."
        action={
          <Button variant="primary">
            <Plus className="mr-2 h-4 w-4" /> Generate Link
          </Button>
        }
      />

      <div className="grid gap-6 md:grid-cols-3">
        {links.map((link) => (
          <Card key={link.id} className="relative hover:shadow-md transition-shadow">
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10 text-purple-600">
                <LinkIcon className="h-5 w-5" />
              </div>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${
                  link.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                }`}
              >
                {link.is_active ? 'Active' : 'Expired'}
              </span>
            </CardHeader>
            <CardContent className="mt-3 space-y-4">
              <div>
                <CardTitle className="text-lg font-bold">{link.title}</CardTitle>
                <CardDescription className="mt-1.5 line-clamp-2">{link.description}</CardDescription>
              </div>

              <div className="bg-secondary/50 rounded-lg p-2.5 font-mono text-xs text-muted-foreground flex justify-between items-center">
                <span>/upload/{link.token}</span>
                <Eye className="h-3.5 w-3.5 text-muted-foreground/60 cursor-pointer hover:text-foreground" />
              </div>

              <div className="border-t border-border pt-4 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <Users className="h-3.5 w-3.5" /> Submissions: {link.submission_count}/{link.max_submissions}
                </div>
                <div className="flex items-center gap-1.5 justify-end">
                  <Calendar className="h-3.5 w-3.5" /> Expiry: {link.expires_at}
                </div>
              </div>
            </CardContent>
          </Card>
          ))}
      </div>
    </div>
  )
}
